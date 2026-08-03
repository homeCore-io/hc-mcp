"""Device command tools (Phase 2).

Two tools, both write-gated behind ``HC_MCP_ALLOW_WRITE=device_commands``
(also satisfied by ``HC_MCP_ALLOW_WRITE=all``):

- ``command_device``: dispatch a command to a single device. Body is the
  plugin's action-specific payload (e.g. ``{"action": "set", "on": true,
  "brightness": 200}`` for a light). Maps to PATCH /devices/{id}/state.
- ``bulk_command``: fan out the same OR per-device commands across many
  devices. Each entry is dispatched independently; failures are collected
  and reported per-device rather than aborting the batch.
"""

from __future__ import annotations

import asyncio

import httpx
from mcp.server.fastmcp import FastMCP

from ..permissions import ensure_write
from ..server_state import client

WRITE_CATEGORY = "device_commands"


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def command_device(device_id: str, command: dict) -> dict:
        """Issue a command to a single device.

        ``command`` is the JSON body forwarded to the plugin via core's
        PATCH /devices/{id}/state. Shape is plugin-specific — typically
        ``{"action": "set", "<attr>": <value>, ...}``. Use
        ``device_state(device_id)`` first to see the device's current
        attributes and ``plugin_capabilities(plugin_id)`` to learn the
        valid command shapes.

        Examples:
          - Light on full:    ``{"action": "set", "on": true, "brightness": 255}``
          - Light off:        ``{"action": "set", "on": false}``
          - Lock a door:      ``{"action": "set", "locked": true}``
          - Activate scene:   ``{"action": "activate"}``

        Returns the core response body (typically ``{"ok": true,
        "device_id": "..."}`` or the updated state). Raises on HTTP 4xx
        or 5xx with the response detail surfaced.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().command_device(device_id, command)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"command_device failed: HTTP {e.response.status_code} — "
                f"{e.response.text or '(empty body)'}"
            ) from e

    @mcp.tool()
    async def bulk_command(commands: list[dict]) -> dict:
        """Fan out commands across many devices in parallel.

        Each entry in ``commands`` is ``{"device_id": "<id>", "command":
        {...}}``. Commands run concurrently; per-device failures are
        captured rather than aborting the batch.

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
        thermostat to 68" patterns. The response shape lets you see
        exactly which devices acknowledged and which didn't.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        if not commands:
            return {"total": 0, "succeeded": 0, "failed": 0, "results": []}

        c = client()

        async def _one(entry: dict) -> dict:
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
                return {
                    "device_id": device_id,
                    "ok": False,
                    "error": f"HTTP {e.response.status_code} — {e.response.text or '(empty body)'}",
                }
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
