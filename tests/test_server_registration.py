"""The server assembles, and every tool it advertises is well-formed.

This is the cheap test that would have caught the most: a syntax error, a
bad decorator, a duplicate tool name, or a missing import in any of the
eight tool modules shows up here without a homeCore instance anywhere near
it. No network — the client is constructed but never called.
"""

from __future__ import annotations

import pytest

from hc_mcp.config import Config
from hc_mcp.homecore_client import HomeCoreClient
from hc_mcp.server import build_server

# Every tool the server is expected to expose. Written out rather than
# derived, so that *losing* a tool fails the test — a set compared against
# itself always passes.
EXPECTED = {
    # read-only
    "system_health",
    "list_plugins",
    "plugin_status",
    "plugin_capabilities",
    "list_devices",
    "device_state",
    "device_history",
    "list_rules",
    "get_rule",
    "rule_test",
    "rule_firings",
    "recent_events",
    "core_logs",
    "plugin_logs",
    "find_recent_errors",
    "correlation_trace",
    "broker_diagnose",
    # write — gated by permissions.ensure_write
    "command_device",
    "bulk_command",
    "create_rule",
    "update_rule",
    "delete_rule",
    "enable_rule",
    "disable_rule",
    "list_plugin_actions",
    "invoke_plugin_action",
    "await_streaming_plugin_action",
}


@pytest.fixture
def server():
    return build_server(HomeCoreClient(Config("http://127.0.0.1:1", "test-key", 1.0)))


async def _tools(server):
    return await server.list_tools()


@pytest.mark.asyncio
async def test_every_expected_tool_is_registered(server):
    names = {t.name for t in await _tools(server)}
    assert names == EXPECTED, (
        f"missing: {sorted(EXPECTED - names)}  unexpected: {sorted(names - EXPECTED)}"
    )


@pytest.mark.asyncio
async def test_tool_names_are_unique(server):
    names = [t.name for t in await _tools(server)]
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_every_tool_is_described(server):
    # The description is the whole interface as far as a model is concerned;
    # an undescribed tool is one it will use wrongly or not at all.
    undescribed = [t.name for t in await _tools(server) if not (t.description or "").strip()]
    assert undescribed == []


@pytest.mark.asyncio
async def test_every_tool_has_an_input_schema(server):
    for t in await _tools(server):
        assert t.inputSchema is not None, t.name
        assert t.inputSchema.get("type") == "object", t.name


def test_building_twice_does_not_accumulate_tools():
    # build_server sets module-level client state; make sure it is not also
    # leaking tool registrations between servers.
    a = build_server(HomeCoreClient(Config("http://127.0.0.1:1", "k", 1.0)))
    b = build_server(HomeCoreClient(Config("http://127.0.0.1:1", "k", 1.0)))
    import asyncio

    assert len(asyncio.run(a.list_tools())) == len(asyncio.run(b.list_tools()))
