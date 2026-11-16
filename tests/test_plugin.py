"""hc-mcp as homeCore's Assistant plugin, driven through its MQTT management
topic the way core drives it. No broker: the MQTT client is a mock, the model
and homeCore are fakes."""

from __future__ import annotations

import json
import os
import threading
from unittest.mock import MagicMock

import pytest
from fakes import ADMIN, MEMBER, FakeHomeCore, FakeProvider
from homecore_plugin_sdk import ui

from hc_mcp import plugin as plugin_mod
from hc_mcp.plugin import AssistantPlugin, capabilities, data_dir_for
from hc_mcp.provider import NO_KEY, ProviderError

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")


@pytest.fixture
def made(tmp_path, monkeypatch):
    """A plugin with a mock MQTT client, a fake model and a fake homeCore."""
    monkeypatch.setattr(plugin_mod, "ACCESS_WAIT_SECS", 0.05)
    p = AssistantPlugin(data_dir=str(tmp_path), broker_host="127.0.0.1", broker_port=1883)
    p._client = MagicMock()
    hc = FakeHomeCore()
    script: list[dict] = []
    providers: list[FakeProvider] = []

    def provider_factory(settings, api_key=None, model=None):
        key = api_key if api_key is not None else settings.api_key
        if not key:
            raise ProviderError(NO_KEY, "no_key")
        fp = FakeProvider(script)
        providers.append(fp)
        return fp

    p.provider_factory = provider_factory
    p.client_factory = lambda access: hc
    p.enable_management(interval_secs=3600, capabilities=capabilities())
    return p, hc, script, providers


def send(p, action: str, request_id: str = "r1", **body) -> None:
    msg = MagicMock()
    msg.topic = f"homecore/plugins/{p.PLUGIN_ID}/manage/cmd"
    msg.payload = json.dumps({"action": action, "request_id": request_id, **body}).encode()
    p._on_message_handler(msg)


def published(p, suffix: str) -> list[dict]:
    out = []
    for c in p._client.publish.call_args_list:
        topic, payload = c[0][:2]
        if topic.endswith(suffix) and payload:
            out.append(json.loads(payload))
    return out


def reply(p, request_id: str = "r1") -> dict:
    return [r for r in published(p, "/manage/response") if r["request_id"] == request_id][-1]


def stream(p) -> list[dict]:
    return published(p, "/events")


def join_actions() -> None:
    for t in threading.enumerate():
        if t.name.startswith("hc-action-"):
            t.join(timeout=10)


def grant(p) -> None:
    send(p, "api_access", "ra", url="http://127.0.0.1:8080/api/v1", key="hc_sk_plugin",
         scopes=plugin_mod.API_SCOPES)  # fmt: skip


# ── the manifest ────────────────────────────────────────────────────────────


def test_the_manifest_asks_for_rest_access_and_declares_the_chat(made):
    p, *_ = made
    manifest = published(p, "/capabilities")[-1]
    assert manifest["plugin_id"] == "plugin.mcp"
    assert set(manifest["api_scopes"]) >= {
        "devices:read",
        "devices:command",
        "scenes:run",
        "automations:write",
        "plugins:read",
        "audit:read",
    }
    assert "users:write" not in manifest["api_scopes"]
    actions = {a["id"]: a for a in manifest["actions"]}
    chat = actions["chat"]
    assert chat["stream"] and chat["cancelable"] and chat["concurrency"] == "multi"
    assert chat["requires_role"] == "signed_in"
    assert actions["settings_set"]["requires_role"] == "admin"
    assert actions["test_key"]["requires_role"] == "admin"
    assert actions["chats"]["requires_role"] == "signed_in"


def test_the_ui_folder_is_a_valid_plugin_ui():
    loaded = ui.load(UI_DIR, "0.1.1").to_dict()
    slots = {s["slot"]: s for s in loaded["slots"]}
    assert slots["app.assistant"]["element"] == "hc-mcp-chat"
    assert slots["app.assistant"]["label"] == "Ask"
    assert slots["plugin.page"]["element"] == "hc-mcp-settings"


# ── settings ────────────────────────────────────────────────────────────────


def test_settings_never_return_the_key(made):
    p, *_ = made
    send(p, "settings_set", "r1", caller=ADMIN, api_key="sk-ant-very-secret", security=True)
    assert reply(p)["ok"] is True
    send(p, "settings_get", "r2", caller=ADMIN)
    got = reply(p, "r2")
    assert got["api_key_set"] is True and got["security"] is True
    everything = json.dumps([c[0] for c in p._client.publish.call_args_list])
    assert "sk-ant-very-secret" not in everything


def test_only_an_admin_changes_settings(made):
    p, *_ = made
    send(p, "settings_set", "r1", caller=MEMBER, security=True)
    assert reply(p)["ok"] is False
    send(p, "settings_get", "r2", caller=ADMIN)
    assert reply(p, "r2")["security"] is False


def test_a_bad_setting_is_refused(made):
    p, *_ = made
    send(p, "settings_set", "r1", caller=ADMIN, model="gpt-5")
    assert reply(p)["ok"] is False and "unknown model" in reply(p)["error"]


def test_testing_the_key(made):
    p, *_ = made
    send(p, "test_key", "r1", caller=ADMIN)
    assert reply(p)["ok"] is False and "API key" in reply(p)["error"]
    send(p, "test_key", "r2", caller=ADMIN, api_key="sk-ant-new")
    assert reply(p, "r2")["ok"] is True


def test_rest_access_shows_in_settings(made):
    p, *_ = made
    send(p, "settings_get", "r1", caller=ADMIN)
    assert reply(p)["rest_access"]["ready"] is False
    grant(p)
    send(p, "settings_get", "r2", caller=ADMIN)
    assert reply(p, "r2")["rest_access"]["ready"] is True
    assert "hc_sk_plugin" not in json.dumps(reply(p, "r2"))


# ── the chat ────────────────────────────────────────────────────────────────


def test_a_chat_without_a_key_says_so_and_the_plugin_stays_up(made):
    p, *_ = made
    grant(p)
    send(p, "chat", "c1", caller=MEMBER, text="hi")
    join_actions()
    last = stream(p)[-1]
    assert last["stage"] == "error"
    assert last["message"] == NO_KEY
    # Still answering.
    send(p, "ping", "r9")
    assert reply(p, "r9")["status"] == "ok"


def test_a_chat_before_rest_access_says_so(made):
    p, *_ = made
    send(p, "settings_set", "r1", caller=ADMIN, api_key="k")
    send(p, "chat", "c1", caller=MEMBER, text="hi")
    join_actions()
    assert stream(p)[-1]["stage"] == "error"
    assert "waiting for homeCore" in stream(p)[-1]["message"]


def test_a_chat_without_a_caller_is_refused(made):
    p, *_ = made
    send(p, "chat", "c1", text="hi")
    join_actions()
    assert "didn't say who is asking" in stream(p)[-1]["message"]


def test_a_chat_end_to_end_and_kept_for_its_owner_only(made):
    p, hc, script, providers = made
    send(p, "settings_set", "r1", caller=ADMIN, api_key="k")
    grant(p)
    script += [{"tools": [("list_devices", {})]}, {"text": "Three lights are on."}]
    send(p, "chat", "c1", caller=MEMBER, text="Anything on?", units="F")
    join_actions()
    events = stream(p)
    assert events[-1]["stage"] == "complete"
    done = events[-1]["data"]
    assert done["title"] == "Anything on?"
    assert any(e["stage"] == "progress" and e["data"]["kind"] == "text" for e in events)
    assert any(e["stage"] == "item" and e["data"]["kind"] == "step" for e in events)
    # The caller's own scopes and units reached the model; the caller never
    # reached the params.
    sent = providers[-1].requests[0]
    assert "create_rule" not in {t["name"] for t in sent["tools"]}
    assert "°F" in sent["system"]
    assert hc.closed

    send(p, "chats", "l1", caller=MEMBER)
    assert [c["id"] for c in reply(p, "l1")["chats"]] == [done["chat_id"]]
    send(p, "chats", "l2", caller=ADMIN)
    assert reply(p, "l2")["chats"] == []
    send(p, "chat_get", "g1", caller=ADMIN, chat_id=done["chat_id"])
    assert reply(p, "g1")["ok"] is False
    send(p, "chat_get", "g2", caller=MEMBER, chat_id=done["chat_id"])
    turns = reply(p, "g2")["chat"]["turns"]
    assert turns[0] == {"role": "user", "text": "Anything on?"}
    assert "api_messages" not in reply(p, "g2")["chat"]
    send(p, "chat_delete", "x1", caller=MEMBER, chat_id=done["chat_id"])
    assert reply(p, "x1")["ok"] is True
    send(p, "chats", "l3", caller=MEMBER)
    assert reply(p, "l3")["chats"] == []


def test_the_confirm_card_is_answered_through_respond(made):
    p, hc, script, _ = made
    send(p, "settings_set", "r1", caller=ADMIN, api_key="k")
    grant(p)
    script += [
        {"tools": [("command_device", {"device_id": "light.lamp", "command": {"on": False}})]},
        {"text": "Done."},
    ]
    send(p, "chat", "c1", caller=MEMBER, text="Lamp off")

    def answer_when_asked():
        import time

        for _ in range(200):
            if any(e["stage"] == "awaiting_user" for e in stream(p)):
                send(p, "respond", "a1", target_request_id="c1", response={"choice": "go"})
                return
            time.sleep(0.02)

    t = threading.Thread(target=answer_when_asked)
    t.start()
    t.join(timeout=10)
    join_actions()
    card = next(e for e in stream(p) if e["stage"] == "awaiting_user")
    assert card["data"]["preview"]["title"] == "Turn off Floor lamp"
    assert hc.commands == [("light.lamp", {"on": False})]
    assert stream(p)[-1]["stage"] == "complete"


# ── where things are kept ───────────────────────────────────────────────────


def test_data_dir_in_a_runtime_survives_upgrades(tmp_path, monkeypatch):
    monkeypatch.delenv("HC_MCP_DATA_DIR", raising=False)
    cfg = tmp_path / "plugins" / "plugin.mcp" / "0.1.1" / "config.toml"
    assert data_dir_for(str(cfg)) == str(tmp_path / "plugins" / "plugin.mcp" / "data")


def test_data_dir_by_hand_and_by_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("HC_MCP_DATA_DIR", raising=False)
    cfg = tmp_path / "config.toml"
    assert data_dir_for(str(cfg)) == str(tmp_path / "hc-mcp-data")
    assert data_dir_for(str(cfg), {"assistant": {"data_dir": "keep"}}) == str(tmp_path / "keep")
    monkeypatch.setenv("HC_MCP_DATA_DIR", "/elsewhere")
    assert data_dir_for(str(cfg)) == "/elsewhere"
