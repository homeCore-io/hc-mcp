"""Device command tools (Phase 2).

Two tools, both write-gated behind ``HC_MCP_ALLOW_WRITE=device_commands``
(also satisfied by ``HC_MCP_ALLOW_WRITE=all``):

- ``command_device``: dispatch a command to a single device. Body is an
  attribute write (e.g. ``{"on": true, "brightness_pct": 80}`` for a light)
  or a declared action (``{"action": "<name>", ...params}``). Maps to
  PATCH /devices/{id}/state.
- ``bulk_command``: fan out the same OR per-device commands across many
  devices. Each entry is dispatched independently; failures are collected
  and reported per-device rather than aborting the batch.
"""

from __future__ import annotations

import asyncio

import httpx

from ..server_state import client

WRITE_CATEGORY = "device_commands"

#: bulk_command sends at most this many commands at once.
MAX_PARALLEL = 8


def _why(device_id: str, e: httpx.HTTPStatusError) -> str:
    if e.response.status_code == 404:
        return f"homeCore has no device {device_id!r}; nothing was sent. list_devices has the ids."
    return f"HTTP {e.response.status_code} — {e.response.text or '(empty body)'}"


async def command_device(device_id: str, command: dict) -> dict:
    """Issue a command to a single device.

    ``command`` is the JSON body forwarded to the plugin via core's
    PATCH /devices/{id}/state. It takes one of two shapes:

      - an attribute write — ``{"<attr>": <value>, ...}`` — for any
        attribute the device's schema marks writable;
      - a declared action — ``{"action": "<name>", ...params}`` — for
        actions listed in the device's schema.

    ``{"command": ...}`` is not a valid shape. Use
    ``device_state(device_id)`` first to see the device's attributes,
    which are writable, and its actions.

    Devices share one vocabulary: ``on``, ``brightness_pct`` (0–100),
    ``color_temp`` (kelvin), ``color_rgb`` (``{"r","g","b"}`` 0–255),
    ``transition_ms``, ``locked``, ``position`` (cover, 0–100, 100 open),
    ``volume`` (0–100), ``muted``, ``hvac_mode``, ``fan_mode``,
    ``setpoint`` / ``heat_setpoint`` / ``cool_setpoint`` (°C). Read-only
    terms include ``open``, ``motion``, ``occupied``, ``battery_pct``,
    ``temperature`` (°C), ``humidity``, ``illuminance`` (lux),
    ``hvac_action``. Temperatures are always °C — convert a °F request
    before sending.

    Examples:
      - Light on full:     ``{"on": true, "brightness_pct": 100}``
      - Warm white, fade:  ``{"color_temp": 2700, "transition_ms": 500}``
      - Light off:         ``{"on": false}``
      - Lock a door:       ``{"locked": true}``
      - Heat to 20 °C:     ``{"hvac_mode": "heat", "heat_setpoint": 20}``
      - Activate scene:    ``{"action": "activate"}``
      - Start a timer:     ``{"action": "start", "duration_secs": 600}``

    Returns ``{"status": "accepted", "correlation_id": "..."}``: homeCore
    published the command. It does not mean the device acted; read
    ``device_state`` again, or pass the ``correlation_id`` to
    ``correlation_trace`` to see the state change it caused. A device id
    homeCore doesn't know is refused (HTTP 404) and nothing is sent.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
    ``all``); a lock, door, garage or other device that counts for
    security also needs ``security`` in it."""
    try:
        return await client().command_device(device_id, command)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"command_device failed: {_why(device_id, e)}") from e


async def bulk_command(commands: list[dict]) -> dict:
    """Fan out commands across many devices in parallel.

    Each entry in ``commands`` is ``{"device_id": "<id>", "command":
    {...}}``, where the inner body takes the same shapes as
    ``command_device`` (an attribute write or ``{"action": ...}``).
    Commands run concurrently, at most 8 at a time; per-device failures
    are captured rather than aborting the batch.

    Returns:
      ``{
        "total": <int>,
        "succeeded": <int>,
        "failed": <int>,
        "results": [
          {"device_id": "...", "ok": true,  "response": {...}},
          {"device_id": "...", "ok": false, "error": "..."},
          ...
        ]
      }``

    Use for "turn off everything in the living room" or "set every
    thermostat to 20 °C" patterns (setpoints are °C; convert 68 °F to
    20 °C first). The response shape lets you see
    exactly which devices acknowledged and which didn't.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
    ``all``)."""
    if not commands:
        return {"total": 0, "succeeded": 0, "failed": 0, "results": []}

    c = client()
    gate = asyncio.Semaphore(MAX_PARALLEL)

    async def _one(entry: dict) -> dict:
        async with gate:
            return await _send(entry)

    async def _send(entry: dict) -> dict:
        device_id = entry.get("device_id")
        command = entry.get("command")
        if not isinstance(device_id, str) or not isinstance(command, dict):
            return {
                "device_id": device_id,
                "ok": False,
                "error": "entry must have string device_id and dict command",
            }
        try:
            resp = await c.command_device(device_id, command)
            return {"device_id": device_id, "ok": True, "response": resp}
        except httpx.HTTPStatusError as e:
            return {"device_id": device_id, "ok": False, "error": _why(device_id, e)}
        except Exception as e:  # noqa: BLE001 — surface anything to the caller
            return {"device_id": device_id, "ok": False, "error": str(e)}

    results = await asyncio.gather(*(_one(e) for e in commands))
    succeeded = sum(1 for r in results if r["ok"])
    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }
