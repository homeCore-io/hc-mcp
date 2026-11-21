"""Every tool, once: what it is called, what it does, what it needs.

The MCP server and the in-app chat both serve tools from this list, so a tool
added here is a tool in both (unless it says otherwise with ``mcp`` / ``chat``).
A tool's function is plain: keyword arguments in, JSON-able out, talking to
homeCore through ``server_state.client()``. Its schema is derived from the
function's signature the same way FastMCP derives it, so the two surfaces
cannot disagree about arguments.

Gating differs by surface and lives outside the functions:

- MCP server: a write tool checks ``HC_MCP_ALLOW_WRITE`` (``permissions``),
  as it always has.
- Chat: a tool is offered only if its category is switched on in the
  plugin's settings and the person asking holds its scopes (``for_chat``);
  changes then go through the confirm step in ``chat.py``.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import Prompt
from mcp.server.fastmcp.resources import TextResource
from mcp.server.fastmcp.tools import Tool as _FastTool

from . import guides, security
from .permissions import ensure_write, is_allowed
from .tools import (
    commands,
    devices,
    diagnosis,
    events,
    house,
    operations,
    plugin_actions,
    plugins,
    rules,
    skills,
    system,
    troubleshooting,
)

#: Answers questions. Always on.
READ = "read"
#: Commands devices and runs scenes.
DEVICE_COMMANDS = "device_commands"
#: Makes, changes and deletes automations.
RULE_MUTATIONS = "rule_mutations"
#: Runs another plugin's actions.
PLUGIN_ACTIONS = "plugin_actions"
#: Devices that count for security. Not a tool category of its own: a device
#: command or an automation that touches one needs this switched on as well.
SECURITY = "security"

CATEGORIES = (READ, DEVICE_COMMANDS, RULE_MUTATIONS, PLUGIN_ACTIONS, SECURITY)

MCP_SECURITY_REFUSAL = (
    "hc-mcp: not done. {names} counts for security (locks, doors and the like). "
    "Changing one needs security allowed as well: add it to HC_MCP_ALLOW_WRITE "
    "(for example HC_MCP_ALLOW_WRITE=device_commands,security), or use all."
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Awaitable[Any]]
    category: str = READ
    #: homeCore scopes the person asking must hold (chat).
    scopes: tuple[str, ...] = ()
    #: Only an admin may use it (homeCore checks the role, not a scope).
    admin_only: bool = False
    #: Served by the MCP server / offered in chat.
    mcp: bool = True
    chat: bool = True
    #: The chip the chat shows once it ran ("Looked at 42 devices"), from the
    #: arguments and the result.
    step: Callable[[dict, Any], str] | None = None
    #: What the chat shows while it runs.
    running: str = "Looking"
    extra: dict = field(default_factory=dict)

    @property
    def mutates(self) -> bool:
        return self.category != READ

    @property
    def description(self) -> str:
        return inspect.getdoc(self.fn) or ""

    @property
    def chat_description(self) -> str:
        """The description without the MCP server's environment-variable
        gating note, which means nothing in chat."""
        return self.description.split("Write-gated", 1)[0].rstrip()

    @functools.cached_property
    def input_schema(self) -> dict:
        schema = dict(_FastTool.from_function(self.fn).parameters)
        schema.pop("title", None)
        props = {}
        for name, prop in schema.get("properties", {}).items():
            prop = {k: v for k, v in prop.items() if k != "title"}
            props[name] = prop
        schema["properties"] = props
        return schema

    def mcp_callable(self) -> Callable[..., Awaitable[Any]]:
        if not self.mutates:
            return self.fn

        @functools.wraps(self.fn)
        async def gated(*args: Any, **kwargs: Any) -> Any:
            ensure_write(self.category)
            # The chat's "Locks, doors and security" switch, for the MCP
            # server: a change that touches a security device needs
            # `security` in HC_MCP_ALLOW_WRITE as well as its own category.
            if not is_allowed(SECURITY):
                names = await security.touched(self.name, kwargs)
                if names:
                    raise PermissionError(MCP_SECURITY_REFUSAL.format(names=", ".join(names)))
            return await self.fn(*args, **kwargs)

        return gated


def _count(noun: str, verb: str = "Looked at") -> Callable[[dict, Any], str]:
    def label(_args: dict, result: Any) -> str:
        n = len(result) if isinstance(result, list) else 0
        return f"{verb} {n} {noun if n != 1 else noun.rstrip('s')}"

    return label


def _fixed(text: str) -> Callable[[dict, Any], str]:
    return lambda _args, _result: text


TOOLS: tuple[ToolSpec, ...] = (
    # ── read ──────────────────────────────────────────────────────────────
    ToolSpec("system_health", system.system_health, step=_fixed("Checked homeCore")),
    ToolSpec("list_plugins", plugins.list_plugins, scopes=("plugins:read",),
             step=_count("plugins")),
    ToolSpec("plugin_status", plugins.plugin_status, scopes=("plugins:read",),
             step=_fixed("Checked the plugin")),
    ToolSpec("plugin_capabilities", plugins.plugin_capabilities, scopes=("plugins:read",),
             step=_fixed("Read what the plugin can do")),
    ToolSpec("list_devices", devices.list_devices, scopes=("devices:read",),
             step=_count("devices"), running="Looking at devices"),
    ToolSpec("device_state", devices.device_state, scopes=("devices:read",),
             step=lambda _a, r: f"Checked {house.device_label(r) if isinstance(r, dict) else 'it'}"),
    ToolSpec("device_history", devices.device_history, scopes=("devices:read",),
             step=_fixed("Read its history")),
    ToolSpec("list_rules", rules.list_rules, scopes=("automations:read",),
             step=_count("automations")),
    ToolSpec("get_rule", rules.get_rule, scopes=("automations:read",),
             step=lambda _a, r: f"Read {r.get('name') if isinstance(r, dict) else 'it'}"),
    ToolSpec("rule_test", rules.rule_test, scopes=("automations:read",),
             step=_fixed("Tried it against the house now")),
    ToolSpec("rule_firings", rules.rule_firings, scopes=("automations:read",),
             step=_fixed("Checked what ran")),
    ToolSpec("test_draft_rule", rules.test_draft_rule, scopes=("automations:read",),
             step=_fixed("Tried the draft against the house now")),
    ToolSpec("recent_events", events.recent_events, scopes=("devices:read",),
             step=_fixed("Read recent events")),
    ToolSpec("correlation_trace", events.correlation_trace, scopes=("devices:read",),
             step=_fixed("Followed what happened")),
    ToolSpec("core_logs", troubleshooting.core_logs, admin_only=True, chat=False,
             step=_fixed("Read homeCore's log")),
    ToolSpec("plugin_logs", troubleshooting.plugin_logs, admin_only=True, chat=False,
             step=_fixed("Read the plugin's log")),
    ToolSpec("find_recent_errors", troubleshooting.find_recent_errors, admin_only=True, chat=False,
             step=_fixed("Looked for errors")),
    ToolSpec("broker_diagnose", system.broker_diagnose, scopes=("plugins:read",),
             step=_fixed("Checked the plugins' connections")),
    ToolSpec("plugin_health", diagnosis.plugin_health, scopes=("plugins:read",),
             step=_fixed("Checked how the plugins are doing")),
    ToolSpec("list_alerts", diagnosis.list_alerts, scopes=("devices:read",),
             step=_count("alerts")),
    ToolSpec("audit_log", diagnosis.audit_log, scopes=("audit:read",),
             step=_fixed("Read who changed what")),
    ToolSpec("paused_rules", diagnosis.paused_rules, scopes=("automations:read",),
             step=_fixed("Checked for paused automations")),
    ToolSpec("stale_rule_refs", diagnosis.stale_rule_refs, scopes=("automations:read",),
             step=_fixed("Checked automations for missing devices")),
    ToolSpec("hub_variables", diagnosis.hub_variables, scopes=("automations:read",),
             step=_fixed("Read the hub variables")),
    ToolSpec("orphaned_devices", diagnosis.orphaned_devices, scopes=("devices:read",),
             step=_fixed("Checked for devices no plugin manages")),
    ToolSpec("vocabulary_check", diagnosis.vocabulary_check,
             scopes=("devices:read", "automations:read"),
             step=_fixed("Checked automations against what devices take")),
    ToolSpec("system_versions", diagnosis.system_versions,
             step=_fixed("Read what versions are running")),
    ToolSpec("list_plugin_actions", plugin_actions.list_plugin_actions,
             scopes=("plugins:read",), step=_count("plugin actions", "Found")),
    ToolSpec("query_plugin_action", plugin_actions.query_plugin_action,
             scopes=("devices:read",), step=_fixed("Asked the plugin")),
    # How-to guides. The chat names them in its instructions, so it only reads.
    ToolSpec("list_skills", skills.list_skills, chat=False, step=_count("guides", "Found")),
    ToolSpec("read_skill", skills.read_skill, step=_fixed("Read the guide"),
             running="Reading the guide"),
    # The log tools stay out of chat: homeCore serves logs to admins only,
    # and the plugin's own key is never an admin's.
    # Chat only: the two screen tools.
    ToolSpec("list_scenes", house.list_scenes, scopes=("scenes:read",),
             step=_count("scenes")),
    ToolSpec("list_rooms", house.list_rooms, scopes=("areas:read",),
             step=_count("rooms")),
    ToolSpec("show_devices", house.show_devices, scopes=("devices:read",), mcp=False),
    ToolSpec("suggest_replies", house.suggest_replies, mcp=False),
    # ── device commands ───────────────────────────────────────────────────
    ToolSpec("command_device", commands.command_device, DEVICE_COMMANDS,
             scopes=("devices:command",), step=_fixed("Sent the command")),
    ToolSpec("bulk_command", commands.bulk_command, DEVICE_COMMANDS,
             scopes=("devices:command",),
             step=lambda _a, r: f"Sent {r.get('succeeded', 0)} commands"
             if isinstance(r, dict) else "Sent the commands"),
    ToolSpec("run_scene", house.run_scene, DEVICE_COMMANDS, scopes=("scenes:run",),
             step=_fixed("Ran the scene")),
    ToolSpec("acknowledge_alert", operations.acknowledge_alert, DEVICE_COMMANDS,
             scopes=("devices:command",), step=_fixed("Acknowledged the alert")),
    ToolSpec("room_lights", operations.room_lights, DEVICE_COMMANDS,
             scopes=("devices:command",),
             step=lambda a, _r: "Turned the room's lights " + ("on" if a.get("on") else "off")),
    # ── automations ───────────────────────────────────────────────────────
    ToolSpec("create_rule", rules.create_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Saved the automation")),
    ToolSpec("update_rule", rules.update_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Saved the changes")),
    ToolSpec("delete_rule", rules.delete_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Deleted the automation")),
    ToolSpec("enable_rule", rules.enable_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Turned the automation on")),
    ToolSpec("disable_rule", rules.disable_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Turned the automation off")),
    ToolSpec("resume_rule", operations.resume_rule, RULE_MUTATIONS,
             scopes=("automations:write",), step=_fixed("Resumed the automation")),
    # ── other plugins' actions ────────────────────────────────────────────
    ToolSpec("invoke_plugin_action", plugin_actions.invoke_plugin_action, PLUGIN_ACTIONS,
             scopes=("plugins:write",), step=_fixed("Ran the plugin action")),
    ToolSpec("await_streaming_plugin_action", plugin_actions.await_streaming_plugin_action,
             PLUGIN_ACTIONS, scopes=("plugins:write",), step=_fixed("Ran the plugin action")),
    ToolSpec("plugin_control", operations.plugin_control, PLUGIN_ACTIONS,
             scopes=("plugins:write",),
             step=lambda a, _r: {"start": "Started", "stop": "Stopped"}.get(
                 a.get("op"), "Restarted") + " the plugin"),
    ToolSpec("set_plugin_log_level", operations.set_plugin_log_level, PLUGIN_ACTIONS,
             scopes=("plugins:write",), step=_fixed("Changed the plugin's log level")),
)  # fmt: skip

BY_NAME = {t.name: t for t in TOOLS}


def register_mcp(mcp: FastMCP) -> None:
    """Attach every MCP tool to *mcp*, under the names it has always had,
    and the skills as prompts and resources."""
    for spec in TOOLS:
        if spec.mcp:
            mcp.add_tool(spec.mcp_callable(), name=spec.name, description=spec.description)
    register_skills(mcp)


def _skill_prompt(name: str) -> Callable[[], str]:
    def prompt() -> str:
        return guides.body(name)

    return prompt


def register_skills(mcp: FastMCP) -> None:
    """Each skill as a prompt (its SKILL.md, to start a conversation with)
    and each of its files as a resource (homecore-skill://<skill>/<file>)."""
    for skill in guides.skills():
        mcp.add_prompt(
            Prompt.from_function(
                _skill_prompt(skill.name), name=skill.name, description=skill.description
            )
        )
        for file in skill.files:
            mcp.add_resource(
                TextResource(
                    uri=guides.uri(skill.name, file),
                    name=f"{skill.name}/{file}",
                    description=skill.description if file == "SKILL.md" else None,
                    mime_type="text/markdown",
                    text=guides.read(skill.name, file),
                )
            )


def allowed_in_chat(
    spec: ToolSpec,
    *,
    scopes: Iterable[str],
    role: str | None,
    enabled: Iterable[str],
) -> bool:
    """Whether the chat may offer *spec* to someone holding *scopes* in
    *role*, with the categories in *enabled* switched on."""
    if not spec.chat:
        return False
    if spec.admin_only and role != "admin":
        return False
    if spec.category != READ and spec.category not in set(enabled):
        return False
    held = set(scopes)
    return all(s in held for s in spec.scopes)


def for_chat(
    *,
    scopes: Iterable[str],
    role: str | None,
    enabled: Iterable[str],
    key_scopes: Iterable[str] | None = None,
) -> list[ToolSpec]:
    """The tools the chat offers this person.

    *key_scopes* are what homeCore granted the plugin's own key; a tool that
    needs more than that would only fail, so it is left out too.
    """
    scopes = set(scopes)
    if key_scopes is not None:
        scopes &= set(key_scopes)
    enabled = set(enabled)
    return [t for t in TOOLS if allowed_in_chat(t, scopes=scopes, role=role, enabled=enabled)]
