"""One registry for both surfaces, and who the chat offers what."""

from __future__ import annotations

import pytest
from fakes import ADMIN, MEMBER, READ_ONLY

from hc_mcp import registry
from hc_mcp.chat import chat_schema

ALL_ON = {"device_commands", "rule_mutations", "plugin_actions"}


def names(**kw) -> set[str]:
    return {t.name for t in registry.for_chat(**kw)}


def test_every_tool_has_a_known_category_and_a_schema():
    for t in registry.TOOLS:
        assert t.category in registry.CATEGORIES, t.name
        assert t.input_schema["type"] == "object", t.name
        assert t.description.strip(), t.name
        assert t.mutates == (t.category != registry.READ)


def test_chat_descriptions_drop_the_mcp_gating_note():
    spec = registry.BY_NAME["command_device"]
    assert "Write-gated" in spec.description
    assert "Write-gated" not in spec.chat_description
    assert "HC_MCP_ALLOW_WRITE" not in spec.chat_description


def test_chat_only_tools_stay_off_the_mcp_server():
    # The two screen tools draw in the chat; scenes and rooms are on both
    # since 2026-11-21 (core's own scenes can't be run through command_device).
    mcp_names = {t.name for t in registry.TOOLS if t.mcp}
    assert not mcp_names & {"show_devices", "suggest_replies"}
    assert {"list_scenes", "run_scene", "list_rooms"} <= mcp_names


def test_an_admin_with_everything_on_gets_every_chat_tool():
    got = names(scopes=ADMIN["scopes"], role="admin", enabled=ALL_ON)
    assert got == {t.name for t in registry.TOOLS if t.chat}


def test_answering_needs_no_switch():
    got = names(scopes=READ_ONLY["scopes"], role="read_only", enabled=set())
    assert {"list_devices", "device_state", "list_rules", "get_rule"} <= got
    assert not any(registry.BY_NAME[n].mutates for n in got)


@pytest.mark.parametrize(
    "caller, enabled, present, absent",
    [
        # A household member commands devices but never authors anything,
        # even with authoring switched on.
        (MEMBER, ALL_ON, {"command_device", "run_scene"}, {"create_rule", "list_plugins"}),
        # Switched off in settings: gone even for an admin.
        (ADMIN, {"rule_mutations"}, {"create_rule"}, {"command_device", "run_scene"}),
        (ADMIN, set(), {"list_devices"}, {"create_rule", "invoke_plugin_action"}),
    ],
)
def test_scopes_and_switches_both_must_allow(caller, enabled, present, absent):
    got = names(scopes=caller["scopes"], role=caller["role"], enabled=enabled)
    assert present <= got
    assert not absent & got


def test_the_plugins_own_key_limits_too():
    got = names(scopes=ADMIN["scopes"], role="admin", enabled=ALL_ON,
                key_scopes=["devices:read"])  # fmt: skip
    assert "list_devices" in got
    assert "command_device" not in got and "list_rules" not in got


def test_log_tools_are_mcp_only():
    got = names(scopes=ADMIN["scopes"], role="admin", enabled=ALL_ON)
    assert not got & {"core_logs", "plugin_logs", "find_recent_errors"}


def test_admin_only_tools_need_the_admin_role():
    spec = registry.ToolSpec("x", registry.BY_NAME["list_devices"].fn, admin_only=True)
    assert registry.allowed_in_chat(spec, scopes=ADMIN["scopes"], role="admin", enabled=set())
    assert not registry.allowed_in_chat(spec, scopes=ADMIN["scopes"], role="user", enabled=set())


def test_drafting_an_automation_requires_plain_words():
    schema = chat_schema(registry.BY_NAME["create_rule"])
    assert "explain" in schema["required"]
    # The MCP schema is untouched.
    assert "explain" not in registry.BY_NAME["create_rule"].input_schema["properties"]
