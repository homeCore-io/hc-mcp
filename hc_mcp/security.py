"""Which security devices a change would touch.

A device counts for security by its own ``security`` choice, else its type
(``house.is_security``): locks, doors, windows, covers, garages and the like.
Changing one needs the ``security`` switch as well as the tool's own
category, on both surfaces: the chat's "Locks, doors and security" setting,
and ``security`` in ``HC_MCP_ALLOW_WRITE`` for the MCP server. Both ask
``touched`` and refuse when it names anything.
"""

from __future__ import annotations

from typing import Any

import httpx

from .tools import house

#: Tools that change an automation, which touches whatever the rule names.
RULE_TOOLS = ("create_rule", "update_rule", "delete_rule", "enable_rule", "disable_rule")
#: Tools that run another plugin's action.
PLUGIN_ACTION_TOOLS = ("invoke_plugin_action", "await_streaming_plugin_action")

CHECKED = ("command_device", "bulk_command", "run_scene", *RULE_TOOLS, *PLUGIN_ACTION_TOOLS)


def strings_in(value: Any) -> set[str]:
    """Every string anywhere in *value*: how an automation's devices are
    found without knowing every trigger and action's shape."""
    out: set[str] = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            stack.extend(v.keys())
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
    return out


async def touched(tool: str, args: dict) -> list[str]:
    """The names of the security devices *tool* called with *args* would
    touch, sorted; empty when it touches none."""
    if tool not in CHECKED:
        return []
    from .server_state import client

    c = client()
    devices = await c.list_devices()
    secure = {d.get("device_id"): d for d in devices if house.is_security(d)}
    if not secure:
        return []

    ids: set[str] = set()
    if tool == "command_device":
        ids = {args.get("device_id")} & secure.keys()
    elif tool == "bulk_command":
        ids = {e.get("device_id") for e in args.get("commands") or [] if isinstance(e, dict)}
        ids &= secure.keys()
    elif tool == "run_scene":
        scenes = await c.list_scenes()
        scene = next((s for s in scenes if s.get("id") == args.get("scene_id")), None)
        ids = set((scene or {}).get("states", {})) & secure.keys()
    elif tool in RULE_TOOLS:
        rule = args.get("rule")
        if rule is None and args.get("rule_id"):
            try:
                rule = await c.get_automation(args["rule_id"])
            except httpx.HTTPError:
                rule = None
        ids = strings_in(rule) & secure.keys()
    elif tool in PLUGIN_ACTION_TOOLS:
        ids = await _plugin_action_touches(c, args, secure)
    return sorted(house.device_label(secure[i]) for i in ids)


async def _plugin_action_touches(c: Any, args: dict, secure: dict[str, dict]) -> set[str]:
    """A plugin action touches the security devices its params name. One
    that names none still touches every security device its plugin owns,
    because an action such as disarming an alarm acts on them without
    naming one. A read-only action touches nothing."""
    plugin_id = args.get("plugin_id")
    action = args.get("action")
    try:
        caps = await c.get_plugin_capabilities(plugin_id)
        spec = next((a for a in caps.get("actions", []) if a.get("id") == action), None)
    except httpx.HTTPError:
        spec = None
    if spec is not None and is_read_only(spec):
        return set()
    named = strings_in(args.get("params")) & secure.keys()
    if named:
        return named
    return {i for i, d in secure.items() if d.get("plugin_id") == plugin_id}


def is_read_only(action: dict) -> bool:
    """Whether a plugin's action only reads: core answers it on
    ``/plugins/{id}/query`` for anyone who can read devices."""
    return action.get("requires_role") == "read_only" and not action.get("stream")
