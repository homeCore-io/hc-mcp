"""hc-mcp tool functions.

Each module holds plain async functions, one per tool; ``hc_mcp.registry``
lists them with their category and scopes, and both the MCP server and the
in-app chat serve them from there. Tools reach homeCore through
``server_state.client()``.

Read-only: system, plugins, devices, rules (inspection), events,
troubleshooting. Writes: commands, rules (mutation), plugin_actions; gated by
``HC_MCP_ALLOW_WRITE`` on the MCP server and by the plugin's settings and the
caller's scopes in chat. ``house`` is chat only.
"""
