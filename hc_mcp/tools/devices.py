"""Device inspection tools."""

from __future__ import annotations

from ..server_state import client


async def list_devices() -> list[dict]:
    """Every registered device with current state and availability.
    Result rows contain device_id, plugin_id, name, area, device_type,
    attributes, available, last_seen."""
    return await client().list_devices()


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
