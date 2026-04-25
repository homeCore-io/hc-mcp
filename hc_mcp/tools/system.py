"""System health / status tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def system_health() -> dict:
        """Return homeCore overall health: uptime, version, DB sizes,
        plugin/device/rule counts. Use as a first check when investigating
        a "why isn't X working?" question."""
        return await client().system_status()
