"""Device inspection tools."""

from __future__ import annotations

from ..server_state import client
from .house import device_label, device_room


async def list_devices(
    query: str | None = None,
    room: str | None = None,
    device_type: str | None = None,
) -> list[dict]:
    """Registered devices with current state and availability: every one,
    or those matching. Result rows contain device_id, plugin_id, name, area,
    device_type, attributes, available, last_seen.

    Narrow it on a large house, where the whole list is cut short:
    ``query`` matches words in a device's name, id, room or type ("driveway
    camera", "outside lights"; every word must match), ``room`` a room's
    name, ``device_type`` a type such as "light", "camera" or "lock"."""
    devices = await client().list_devices()
    return [d for d in devices if _matches(d, query, room, device_type)]


def _matches(d: dict, query: str | None, room: str | None, device_type: str | None) -> bool:
    here = (device_room(d) or "").lower()
    kind = (d.get("device_type") or "").lower()
    if room and room.strip().lower() not in here:
        return False
    if device_type and device_type.strip().lower() != kind:
        return False
    if query:
        text = " ".join(
            [device_label(d), d.get("name") or "", d.get("device_id") or "", here, kind]
        ).lower()
        # "cameras" finds a camera.
        return all(w in text or w.rstrip("s") in text for w in query.lower().split())
    return True


async def device_state(device_id: str) -> dict:
    """Current state and schema for a single device.

    The device record (attributes, available, area, device_type, ...) with
    ``schema`` added: each attribute's type, unit, range and whether it is
    writable, and the actions the device declares. Read it before
    ``command_device`` to see what can be set. ``schema`` is ``null`` for a
    device that declares none."""
    c = client()
    device = await c.get_device(device_id)
    if isinstance(device, dict):
        device = {**device, "schema": await c.get_device_schema(device_id)}
    return device


async def device_history(
    device_id: str,
    attribute: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Time-series history for a device. Optionally filter to one
    `attribute` and a time window (`from_`/`to` are ISO-8601). `limit`
    defaults to 500 server-side and caps at 5000."""
    return await client().device_history(
        device_id,
        attribute=attribute,
        from_=from_,
        to=to,
        limit=limit,
    )
