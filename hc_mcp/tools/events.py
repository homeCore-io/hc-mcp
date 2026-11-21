"""Event-log tools."""

from __future__ import annotations

from ..server_state import client


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

    Common usage: take the ``correlation_id`` that ``command_device``
    returns (or one from ``recent_events``), then trace every effect.

    NOTE: filtering is client-side because the /events endpoint
    doesn't natively accept a correlation_id query param yet —
    results are bounded by the recent ring buffer."""
    scan_limit = min(limit, 1000)
    events = await client().list_events(limit=scan_limit)

    matches: list[dict] = []
    for ev in events:
        if _correlation_id(ev) == correlation_id:
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


def _correlation_id(row: dict) -> str | None:
    """The correlation id of one ``GET /events`` row.

    A row is ``{seq, event_type, device_id, event: {...}}``. Most events
    carry the id at ``event.correlation_id``; a state change carries it in
    its provenance, ``event.change.correlation_id``."""
    ev = row.get("event")
    if not isinstance(ev, dict):
        return None
    cid = ev.get("correlation_id")
    if cid is None and isinstance(ev.get("change"), dict):
        cid = ev["change"].get("correlation_id")
    return cid
