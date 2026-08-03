"""System health / status tools."""

from __future__ import annotations

import time
from datetime import UTC

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def system_health() -> dict:
        """Return homeCore overall health: uptime, version, DB sizes,
        plugin/device/rule counts. Use as a first check when investigating
        a "why isn't X working?" question."""
        return await client().system_status()

    @mcp.tool()
    async def broker_diagnose() -> dict:
        """Cross-source check of the embedded MQTT broker's health.

        Aggregates:
          - core uptime (proxy for "broker process is up" — broker is
            embedded, dies with core)
          - per-plugin connection state (managed plugins should appear
            with status=active and a recent heartbeat; offline ones
            with stale heartbeats are the typical symptom of an MQTT
            connectivity issue)
          - count of plugins with stale heartbeat (>120s since last)

        Returns a structured report rather than a raw diagnostic dump
        so a follow-up tool can drill into the specific offender (e.g.
        `plugin_logs` for the listed stale plugin)."""
        c = client()
        status, plugins = await _gather(c)

        now = time.time()
        stale_threshold_secs = 120
        stale: list[dict] = []
        active = 0
        offline = 0
        for p in plugins:
            hb = p.get("last_heartbeat")
            if hb is None:
                hb_age = None
            else:
                hb_age = _seconds_since_iso(hb, now)

            if p.get("status") == "active":
                active += 1
                if hb_age is not None and hb_age > stale_threshold_secs:
                    stale.append(
                        {
                            "plugin_id": p.get("plugin_id"),
                            "status": p.get("status"),
                            "last_heartbeat_age_secs": int(hb_age),
                        }
                    )
            else:
                offline += 1

        return {
            "core_uptime_secs": status.get("uptime_seconds"),
            "version": status.get("version"),
            "plugins": {
                "total": len(plugins),
                "active": active,
                "offline": offline,
                "stale_heartbeat": stale,
            },
            "broker_likely_healthy": (
                status.get("uptime_seconds", 0) > 0 and active > 0 and len(stale) == 0
            ),
        }


async def _gather(c) -> tuple[dict, list[dict]]:
    """Pull system_status + list_plugins concurrently."""
    import asyncio

    return await asyncio.gather(
        c.system_status(),
        c.list_plugins(),
    )


def _seconds_since_iso(iso: str, now: float) -> float | None:
    from datetime import datetime

    try:
        # homeCore emits RFC 3339 with a trailing Z, which fromisoformat has
        # accepted natively since 3.11 — this package requires 3.11, so the
        # old `.replace("Z", "+00:00")` dance is gone (ruff FURB162).
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError, AttributeError):
        # TypeError covers a non-string — previously that surfaced as
        # AttributeError from the `.replace()` on the way in, so dropping the
        # replace quietly narrowed what this tolerated. system_health reports
        # on every plugin in one call and must not die on one bad field.
        return None
    # A naive datetime means the timestamp carried no offset at all; treat it
    # as UTC rather than letting .timestamp() silently read it as local time.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return now - dt.timestamp()
