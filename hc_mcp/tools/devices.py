"""Device inspection tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_devices() -> list[dict]:
        """Every registered device with current state and availability.
        Result rows contain device_id, plugin_id, name, area, device_type,
        attributes, available, last_seen."""
        return await client().list_devices()

    @mcp.tool()
    async def device_state(device_id: str) -> dict:
        """Current state + schema for a single device. Includes the
        attribute-level schema so callers can tell which fields are
        commandable vs read-only."""
        return await client().get_device(device_id)

    @mcp.tool()
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
