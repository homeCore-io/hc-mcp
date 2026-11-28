"""Everyday operations: acknowledge an alert, resume a paused automation,
room lights, and keeping a plugin running.

Each is a small write on one homeCore endpoint, gated like the rest: device
commands for alerts and rooms, rule mutations for resuming, plugin actions
for a plugin's process and log level.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..homecore_client import seg
from ..server_state import client

PLUGIN_OPS = ("start", "stop", "restart")
LOG_LEVELS = ("error", "warn", "info", "debug", "trace")


def _fail(label: str, e: httpx.HTTPStatusError) -> RuntimeError:
    return RuntimeError(
        f"{label} failed: HTTP {e.response.status_code} — {e.response.text or '(empty body)'}"
    )


async def _send(method: str, path: str, label: str, body: dict | None = None) -> Any:
    try:
        return await client().send(method, path, body)
    except httpx.HTTPStatusError as e:
        raise _fail(label, e) from e


async def acknowledge_alert(alert_id: str) -> Any:
    """Acknowledge an alert (from ``list_alerts``): someone has seen it.

    It stays listed, marked acknowledged, until what raised it clears; it
    is not dismissed. homeCore keeps acknowledgements in memory, so after a
    restart an alert that is still true is unacknowledged again.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
    ``all``)."""
    return await _send("POST", f"/alerts/{seg(alert_id)}/acknowledge", "acknowledge_alert")


async def resume_rule(rule_id: str) -> Any:
    """Resume an automation another automation paused (see
    ``paused_rules``), so its own trigger runs it again.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
    ``all``)."""
    return await _send("DELETE", f"/automations/{seg(rule_id)}/pause", "resume_rule")


async def room_lights(room_id: str, on: bool) -> Any:
    """Turn a room's lights off, or back on (``room_id`` from ``list_rooms``).

    Off saves how each light was; on brings them back that way, scenes
    first. With nothing saved, on turns every light in the room on at full
    brightness. Only lights (and switches shown as lights): never locks,
    doors or covers.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
    ``all``)."""
    return await _send("POST", f"/areas/{seg(room_id)}/{'on' if on else 'off'}", "room_lights")


async def plugin_control(plugin_id: str, op: str) -> Any:
    """Start, stop or restart a plugin's process (``op``: start, stop or
    restart). A restart is the first thing to try for a plugin that is
    running but not answering (see ``plugin_health``).

    While a plugin is stopped its devices are offline and nothing it watches
    (locks, sensors, alarms) is reported; ``plugin_control(id, "start")``
    brings it back.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=plugin_actions`` (or
    ``all``)."""
    if op not in PLUGIN_OPS:
        raise ValueError(f"op must be one of {', '.join(PLUGIN_OPS)}")
    return await _send("POST", f"/plugins/{seg(plugin_id)}/{seg(op)}", "plugin_control")


async def set_plugin_log_level(plugin_id: str, level: str) -> Any:
    """Change how much one plugin logs: error, warn, info, debug or trace.

    Takes effect at once and lasts (it is written to the plugin's config).
    Set ``debug`` to see more of what a misbehaving plugin does in
    ``plugin_logs``, and put it back to ``info`` afterwards.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=plugin_actions`` (or
    ``all``)."""
    level = level.lower()
    if level not in LOG_LEVELS:
        raise ValueError(f"level must be one of {', '.join(LOG_LEVELS)}")
    return await _send(
        "PATCH", f"/plugins/{seg(plugin_id)}", "set_plugin_log_level", {"log_level": level}
    )
