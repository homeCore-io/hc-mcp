"""Phase 1 read-only tools.

Each ``register_*`` function attaches its tools to a ``FastMCP`` server.
Server keeps a module-level ``HomeCoreClient`` singleton so tool bodies
stay terse — see ``server.py``.
"""

from . import devices, events, plugin_actions, plugins, rules, system

__all__ = ["devices", "events", "plugin_actions", "plugins", "rules", "system"]
