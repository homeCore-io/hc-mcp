"""Plugin inspection tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_plugins() -> list[dict]:
        """List all known plugins with status, last heartbeat, version,
        and device count. Plugins that have published a capability manifest
        also show declared actions."""
        return await client().list_plugins()

    @mcp.tool()
    async def plugin_status(plugin_id: str) -> dict:
        """Detail for a single plugin. Use after `list_plugins` to drill
        into a specific one. The returned record includes `capabilities`
        (declared actions) when the plugin has published a manifest."""
        return await client().get_plugin(plugin_id)

    @mcp.tool()
    async def plugin_capabilities(plugin_id: str) -> dict:
        """Just the capability manifest for a plugin (404 if not yet
        published). Use to discover what plugin-specific commands exist —
        each action carries id, label, params schema, and `requires_role`."""
        return await client().get_plugin_capabilities(plugin_id)
