"""hc-mcp tool modules.

Each module's ``register(mcp)`` function attaches its tools to a
``FastMCP`` server. The server keeps a module-level ``HomeCoreClient``
singleton so tool bodies stay terse — see ``server.py``.

Phase 1 (read-only): system, plugins, devices, rules, events,
troubleshooting. Phase 2 (write — gated via permissions.ensure_write):
commands, mutation tools in rules. Phase 4 (plugin actions): plugin_actions.
"""

from . import (
    commands,
    devices,
    events,
    plugin_actions,
    plugins,
    rules,
    system,
    troubleshooting,
)

__all__ = [
    "commands",
    "devices",
    "events",
    "plugin_actions",
    "plugins",
    "rules",
    "system",
    "troubleshooting",
]
