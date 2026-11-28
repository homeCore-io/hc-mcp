"""The MCP tools against a stand-in homeCore: the security check on the MCP
surface, the log tools on GET /logs, following a command, and the rest of
what the 2026-11-21 audit found broken."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fakes import FakeHomeCore

from hc_mcp import security
from hc_mcp.registry import BY_NAME
from hc_mcp.server_state import using_client
from hc_mcp.tools import (
    commands,
    devices,
    diagnosis,
    events,
    plugin_actions,
    rules,
    troubleshooting,
)


def _status(code: int, path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://hc/api/v1{path}")
    return httpx.HTTPStatusError(
        str(code), request=request, response=httpx.Response(code, request=request)
    )


class ToolHomeCore(FakeHomeCore):
    """FakeHomeCore plus the calls the MCP tools make."""

    def __init__(self) -> None:
        super().__init__()
        self.devices.append(
            {"device_id": "alarm.house", "name": "House alarm", "plugin_id": "plugin.alarm",
             "device_type": "alarm", "security": True, "available": True, "attributes": {}}
        )  # fmt: skip
        self.queried: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str]] = []
        self.logs_args: dict | None = None
        self.logs_status = 200
        self.in_flight = 0
        self.most_in_flight = 0

    async def command_device(self, device_id: str, command: dict) -> dict:
        if device_id not in {d["device_id"] for d in self.devices}:
            raise _status(404, f"/devices/{device_id}/state")
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        self.commands.append((device_id, command))
        return {"status": "accepted", "correlation_id": "c-1"}

    async def get_device_schema(self, device_id: str) -> dict | None:
        return {"attributes": {"on": {"type": "boolean"}}} if device_id == "light.lamp" else None

    async def get_plugin_capabilities(self, plugin_id: str) -> dict:
        return {
            "actions": [
                {"id": "disarm", "requires_role": "user"},
                {"id": "status", "requires_role": "read_only"},
            ]
        }

    async def query_plugin(self, plugin_id: str, action: str, params=None) -> dict:
        self.queried.append((plugin_id, action))
        return {"ok": True}

    async def send_plugin_command(self, plugin_id: str, action: str, params=None) -> dict:
        self.sent.append((plugin_id, action))
        return {"ok": True}

    async def logs(self, **kwargs) -> dict:
        self.logs_args = kwargs
        if self.logs_status != 200:
            raise _status(self.logs_status, "/logs")
        return {
            "count": 3,
            "lines": [
                {"level": "WARN", "target": "hc_core", "message": "slow rule"},
                {"level": "ERROR", "target": "hc_hue", "message": "bridge timeout",
                 "fields": {"plugin_id": "plugin.hue"}},
                {"level": "WARN", "target": "hc_core", "message": "slow scene"},
            ],
        }  # fmt: skip

    async def list_events(self, limit: int = 50, **_kw) -> list[dict]:
        # Newest first, the way /events answers.
        return [
            {"seq": 3, "event_type": "device_state_changed", "device_id": "light.lamp",
             "event": {"type": "device_state_changed", "change": {"correlation_id": "c-1"}}},
            {"seq": 2, "event_type": "scene_activated", "event": {"type": "scene_activated"}},
            {"seq": 1, "event_type": "device_command_sent", "device_id": "light.lamp",
             "event": {"type": "device_command_sent", "correlation_id": "c-1"}},
        ]  # fmt: skip

    async def automation_history(self, rule_id: str, limit=None) -> list[dict]:
        return [{"n": i} for i in range(20)]


def run(coro):
    return asyncio.run(coro)


def mcp_tool(name: str):
    return BY_NAME[name].mcp_callable()


# ── security on the MCP surface ───────────────────────────────────────────


def test_an_mcp_command_to_a_lock_needs_security_allowed(monkeypatch):
    hc = ToolHomeCore()
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "device_commands")
    with using_client(hc):
        with pytest.raises(PermissionError, match="Front door lock.*security"):
            run(mcp_tool("command_device")(device_id="lock.front", command={"locked": False}))
        run(mcp_tool("command_device")(device_id="light.lamp", command={"on": False}))
    assert hc.commands == [("light.lamp", {"on": False})]

    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "device_commands,security")
    with using_client(hc):
        run(mcp_tool("command_device")(device_id="lock.front", command={"locked": False}))
    assert hc.commands[-1] == ("lock.front", {"locked": False})


def test_a_bulk_command_with_one_lock_in_it_is_refused_whole(monkeypatch):
    hc = ToolHomeCore()
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "device_commands")
    batch = [
        {"device_id": "light.lamp", "command": {"on": False}},
        {"device_id": "switch.gate", "command": {"on": True}},
    ]
    with using_client(hc), pytest.raises(PermissionError, match="Gate opener"):
        run(mcp_tool("bulk_command")(commands=batch))
    assert hc.commands == []


def test_a_plugin_action_on_a_security_plugin_is_refused_but_a_read_is_not(monkeypatch):
    hc = ToolHomeCore()
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "plugin_actions")
    with using_client(hc):
        # Names no device, but plugin.alarm owns the alarm.
        with pytest.raises(PermissionError, match="House alarm"):
            run(mcp_tool("invoke_plugin_action")(plugin_id="plugin.alarm", action="disarm"))
        run(mcp_tool("invoke_plugin_action")(plugin_id="plugin.alarm", action="status"))
    assert hc.sent == []
    assert hc.queried == [("plugin.alarm", "status")], "read-only goes to /query"


def test_query_plugin_action_only_runs_read_only_actions():
    hc = ToolHomeCore()
    with using_client(hc):
        run(plugin_actions.query_plugin_action("plugin.alarm", "status"))
        with pytest.raises(RuntimeError, match="not a read-only action"):
            run(plugin_actions.query_plugin_action("plugin.alarm", "disarm"))
    assert hc.queried == [("plugin.alarm", "status")]
    assert not BY_NAME["query_plugin_action"].mutates


class RuleHomeCore(ToolHomeCore):
    """Holds one automation that locks the front door."""

    lookup_status = 200

    async def get_automation(self, rule_id: str) -> dict:
        if self.lookup_status != 200:
            raise _status(self.lookup_status, f"/automations/{rule_id}")
        return {"id": rule_id, "actions": [{"action": {"SetDeviceState": {
            "device_id": "lock.front", "state": {"locked": True}}}}]}  # fmt: skip


def test_resuming_or_rewriting_a_lock_automation_counts_for_security():
    hc = RuleHomeCore()
    without = {"name": "Lock up", "actions": []}
    with using_client(hc):
        assert run(security.touched("resume_rule", {"rule_id": "r"})) == ["Front door lock"]
        # The new body leaves the lock out; the automation it replaces doesn't.
        assert run(security.touched("update_rule", {"rule_id": "r", "rule": without})) == [
            "Front door lock"
        ]
        assert run(security.touched("create_rule", {"rule": without})) == []


def test_a_rule_that_cannot_be_looked_up_is_not_let_through():
    hc = RuleHomeCore()
    with using_client(hc):
        hc.lookup_status = 404
        assert run(security.touched("enable_rule", {"rule_id": "r"})) == []
        hc.lookup_status = 503
        with pytest.raises(httpx.HTTPStatusError):
            run(security.touched("enable_rule", {"rule_id": "r"}))


# ── commands ──────────────────────────────────────────────────────────────


def test_bulk_command_sends_at_most_eight_at_once():
    hc = ToolHomeCore()
    hc.devices += [
        {"device_id": f"light.{i}", "device_type": "light", "available": True, "attributes": {}}
        for i in range(30)
    ]
    batch = [{"device_id": f"light.{i}", "command": {"on": True}} for i in range(30)]
    with using_client(hc):
        out = run(commands.bulk_command(batch))
    assert out["succeeded"] == 30
    assert hc.most_in_flight <= commands.MAX_PARALLEL


def test_an_unknown_device_is_named_not_accepted():
    hc = ToolHomeCore()
    with using_client(hc), pytest.raises(RuntimeError, match="no device 'light.lmap'"):
        run(commands.command_device("light.lmap", {"on": True}))


# ── following a command ───────────────────────────────────────────────────


def test_correlation_trace_finds_ids_inside_the_event_oldest_first():
    hc = ToolHomeCore()
    with using_client(hc):
        out = run(events.correlation_trace("c-1"))
    assert out["count"] == 2
    assert [m["seq"] for m in out["matches"]] == [1, 3]


def test_device_state_carries_its_schema():
    hc = ToolHomeCore()
    with using_client(hc):
        lamp = run(devices.device_state("light.lamp"))
        lock = run(devices.device_state("lock.front"))
    assert lamp["schema"]["attributes"]["on"]["type"] == "boolean"
    assert lock["schema"] is None


# ── logs ──────────────────────────────────────────────────────────────────


def test_plugin_logs_filter_on_the_server():
    hc = ToolHomeCore()
    with using_client(hc):
        run(troubleshooting.plugin_logs("plugin.hue", lines=20, since="2026-11-21T10:00:00Z"))
    assert hc.logs_args == {
        "level": "info",
        "plugin_id": "plugin.hue",
        "target": None,
        "since": "2026-11-21T10:00:00Z",
        "limit": 20,
    }


def test_find_recent_errors_asks_for_warnings_and_up():
    hc = ToolHomeCore()
    with using_client(hc):
        out = run(troubleshooting.find_recent_errors(lines=10))
    assert hc.logs_args["level"] == "warn"
    assert out["count"] == 3


def test_a_grep_keeps_only_matching_lines():
    hc = ToolHomeCore()
    with using_client(hc):
        out = run(troubleshooting.core_logs(grep="^slow"))
    assert [ln["message"] for ln in out["lines"]] == ["slow rule", "slow scene"]
    assert hc.logs_args["limit"] == troubleshooting.MAX_LINES


def test_a_key_that_is_not_an_admin_is_told_why():
    hc = ToolHomeCore()
    hc.logs_status = 403
    with using_client(hc), pytest.raises(PermissionError, match="users:write"):
        run(troubleshooting.core_logs())


# ── rules ─────────────────────────────────────────────────────────────────


def test_rule_firings_keeps_the_newest_n():
    hc = ToolHomeCore()
    with using_client(hc):
        out = run(rules.rule_firings("rule-1", limit=3))
    assert out == [{"n": 17}, {"n": 18}, {"n": 19}]


def test_test_draft_rule_is_a_read():
    assert not BY_NAME["test_draft_rule"].mutates


# ── diagnosis ─────────────────────────────────────────────────────────────


class DiagnosisHomeCore(ToolHomeCore):
    def __init__(self) -> None:
        super().__init__()
        self.got: list[tuple[str, dict]] = []

    async def list_plugins(self) -> list[dict]:
        return [
            {"plugin_id": "plugin.hue", "status": "active", "enabled": True, "notices": []},
            {"plugin_id": "plugin.yolink", "status": "offline", "enabled": True},
            {"plugin_id": "plugin.old", "status": "offline", "enabled": False},
            {"plugin_id": "plugin.zwave", "status": "active", "enabled": True,
             "notices": [{"level": "warn", "code": "stick", "message": "No Z-Wave stick"}]},
        ]  # fmt: skip

    async def get(self, path: str, **params):
        self.got.append((path, {k: v for k, v in params.items() if v is not None}))
        return []


def test_plugin_health_puts_the_unhappy_first():
    hc = DiagnosisHomeCore()
    with using_client(hc):
        out = run(diagnosis.plugin_health())
    assert [r["plugin_id"] for r in out["attention"]] == ["plugin.yolink", "plugin.zwave"]
    # Turned off and offline is not a problem; active with no notice is fine.
    assert out["ok"] == ["plugin.hue", "plugin.old"]


def test_audit_log_passes_its_filters_and_bounds_the_limit():
    hc = DiagnosisHomeCore()
    with using_client(hc):
        run(diagnosis.audit_log(target_kind="automation", from_="2026-11-20T00:00:00Z",
                                limit=10_000))  # fmt: skip
    assert hc.got == [
        ("/audit", {"target_kind": "automation", "from": "2026-11-20T00:00:00Z", "limit": 500})
    ]


def test_the_diagnosis_tools_are_reads():
    for name in (
        "plugin_health",
        "list_alerts",
        "audit_log",
        "paused_rules",
        "stale_rule_refs",
        "hub_variables",
        "orphaned_devices",
        "vocabulary_check",
        "system_versions",
    ):
        assert not BY_NAME[name].mutates, name  # fmt: skip


def test_a_scene_that_sets_a_lock_needs_security_allowed(monkeypatch):
    hc = ToolHomeCore()
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "device_commands")
    with using_client(hc):
        with pytest.raises(PermissionError, match="Front door lock"):
            run(mcp_tool("run_scene")(scene_id="scene-lockup"))
        run(mcp_tool("run_scene")(scene_id="scene-night"))
    assert hc.commands == [("scene-night", {"action": "activate"})]


def test_a_rotation_on_a_lock_needs_security_allowed(monkeypatch):
    hc = ToolHomeCore()
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "device_commands")
    with using_client(hc):
        with pytest.raises(PermissionError, match="Front door lock"):
            run(mcp_tool("play_rotation")(rotation_id="rot-lock"))
        # Named onto the lock, a harmless rotation is gated too.
        with pytest.raises(PermissionError, match="Front door lock"):
            run(mcp_tool("play_rotation")(rotation_id="rot-lamp", device_id="lock.front"))
        run(mcp_tool("play_rotation")(rotation_id="rot-lamp"))
        run(mcp_tool("skip_rotation")(rotation_id="rot-lamp"))
    assert hc.commands == [
        ("rot-lamp", {"action": "play", "device_id": None}),
        ("rot-lamp", {"action": "advance"}),
    ]


def test_rotations_say_what_plays_now_and_next():
    hc = ToolHomeCore()
    with using_client(hc):
        got = run(mcp_tool("list_rotations")())
    assert got[0] == {
        "id": "rot-lamp",
        "name": "Lamp moods",
        "device_id": "light.lamp",
        "choices": 1,
        "now": "Warm",
        "next": "Cool",
        "missing": [],
    }


# ── operations ────────────────────────────────────────────────────────────


class OpsHomeCore(ToolHomeCore):
    def __init__(self) -> None:
        super().__init__()
        self.sent_raw: list[tuple[str, str, dict | None]] = []

    async def send(self, method: str, path: str, body: dict | None = None):
        self.sent_raw.append((method, path, body))
        return {"ok": True}


def test_operations_call_the_right_endpoints(monkeypatch):
    from hc_mcp.tools import operations

    hc = OpsHomeCore()
    with using_client(hc):
        run(operations.acknowledge_alert("a-1"))
        run(operations.resume_rule("r-1"))
        run(operations.room_lights("kitchen", on=False))
        run(operations.plugin_control("plugin.hue", "restart"))
        run(operations.set_plugin_log_level("plugin.hue", "DEBUG"))
        with pytest.raises(ValueError):
            run(operations.plugin_control("plugin.hue", "delete"))
        with pytest.raises(ValueError):
            run(operations.set_plugin_log_level("plugin.hue", "loud"))
    assert hc.sent_raw == [
        ("POST", "/alerts/a-1/acknowledge", None),
        ("DELETE", "/automations/r-1/pause", None),
        ("POST", "/areas/kitchen/off", None),
        ("POST", "/plugins/plugin.hue/restart", None),
        ("PATCH", "/plugins/plugin.hue", {"log_level": "debug"}),
    ]


def test_operations_are_write_gated(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "")
    hc = OpsHomeCore()
    with using_client(hc), pytest.raises(PermissionError, match="plugin_actions"):
        run(mcp_tool("plugin_control")(plugin_id="plugin.hue", op="restart"))
    assert hc.sent_raw == []
