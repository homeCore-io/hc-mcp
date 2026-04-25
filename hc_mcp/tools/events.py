"""Event-log tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def recent_events(limit: int = 50) -> list[dict]:
        """The last N entries from homeCore's bounded event ring buffer:
        device state changes, rule firings, scene activations,
        plugin lifecycle, and stream stages. Default 50, max 1000.

        For a richer "what happened in this window?" answer combine with
        `device_history` and `rule_firings` for the relevant ids."""
        return await client().list_events(limit=min(limit, 1000))
