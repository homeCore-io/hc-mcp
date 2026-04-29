"""Event-log tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def recent_events(
        limit: int = 50,
        event_type: str | None = None,
        device_id: str | None = None,
    ) -> list[dict]:
        """The last N entries from homeCore's bounded event ring buffer:
        device state changes, rule firings, scene activations,
        plugin lifecycle, and stream stages. Default 50, max 1000.

        Optional filters:
          - event_type: comma-separated names like "device_state_changed,rule_fired"
          - device_id:  only events that mention this device

        For a richer "what happened in this window?" answer combine with
        `device_history` and `rule_firings` for the relevant ids."""
        return await client().list_events(
            limit=min(limit, 1000),
            event_type=event_type,
            device_id=device_id,
        )

    @mcp.tool()
    async def correlation_trace(
        correlation_id: str,
        limit: int = 500,
    ) -> dict:
        """Walk a single command's life cycle by correlation_id.

        homeCore tags every device-command, the resulting state change,
        and any rule firings that branched off it with the same
        correlation_id. Pull a window of recent events, filter to that
        id, and return them in chronological order.

        Result keys:
          - matches:    chronologically-ordered events with this id
          - count:      len(matches)
          - window:     how many events we scanned (limit)
          - truncated:  true if we hit the limit (raise it and re-run if so)

        Common usage: take a correlation_id from `recent_events` or from
        a plugin command response, then trace every effect.

        NOTE: filtering is client-side because the /events endpoint
        doesn't natively accept a correlation_id query param yet —
        results are bounded by the recent ring buffer."""
        scan_limit = min(limit, 1000)
        events = await client().list_events(limit=scan_limit)

        matches: list[dict] = []
        for ev in events:
            # correlation_id may live at the top level or nested in change
            # metadata depending on the event variant.
            cid = ev.get("correlation_id")
            if cid is None:
                change = ev.get("change") or ev.get("current") or {}
                if isinstance(change, dict):
                    cid = change.get("correlation_id")
            if cid == correlation_id:
                matches.append(ev)

        # /events returns most-recent-first; reverse for chronological view.
        matches.reverse()
        return {
            "correlation_id": correlation_id,
            "count": len(matches),
            "window": scan_limit,
            "truncated": len(events) >= scan_limit,
            "matches": matches,
        }
