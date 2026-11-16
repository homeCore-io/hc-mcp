"""The chat loop, against a fake model and a fake homeCore.

What matters most here is what stands between a sentence and a real device:
the confirm card, the security switch, and the person's own scopes.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fakes import ADMIN, MEMBER, READ_ONLY, FakeCtx, FakeHomeCore, FakeProvider

from hc_mcp import chat as chat_mod
from hc_mcp.chat import Turn, command_preview, system_prompt
from hc_mcp.chats import Chat, new_chat_id
from hc_mcp.provider import ProviderError
from hc_mcp.server_state import using_client
from hc_mcp.settings import Settings


def run_turn(script, *, caller=ADMIN, settings=None, answers=(), text="hi", hc=None,
             provider=None, chat=None):  # fmt: skip
    hc = hc or FakeHomeCore()
    ctx = FakeCtx(caller=caller)
    for a in answers:
        ctx.answers.put(a)
    provider = provider or FakeProvider(script)
    chat = chat or Chat(id=new_chat_id(), owner="o")
    turn = Turn(
        ctx=ctx,
        provider=provider,
        settings=settings or Settings(),
        caller=caller,
        chat=chat,
    )

    async def go():
        with using_client(hc):
            return await turn.run(text)

    out = asyncio.run(go())
    return out, ctx, hc, provider, chat


def tool_results(provider: FakeProvider, request: int) -> list[dict]:
    """The tool results the model was sent in request number *request*."""
    last = provider.requests[request]["messages"][-1]
    return last["content"]


OFF_THREE = (
    "bulk_command",
    {
        "commands": [
            {"device_id": d, "command": {"on": False}}
            for d in ("light.island", "light.cabinet", "light.lamp")
        ]
    },
)


# ── answering ───────────────────────────────────────────────────────────────


def test_text_streams_and_the_turn_is_kept():
    out, ctx, _hc, _p, chat = run_turn([{"text": "Three lights are on."}], text="Anything on?")
    assert ctx.text().strip() == "Three lights are on."
    assert out["chat_id"] == chat.id
    assert out["title"] == "Anything on?"
    parts = out["turn"]["parts"]
    assert [p["kind"] for p in parts] == ["text"]
    assert parts[0]["text"] == "Three lights are on. "
    # The conversation as the API takes it: the question and the answer.
    assert [m["role"] for m in chat.api_messages] == ["user", "assistant"]
    assert chat.turns[0] == {"role": "user", "text": "Anything on?"}


def test_a_read_tool_shows_a_step_chip():
    _out, ctx, _hc, provider, _chat = run_turn(
        [{"tools": [("list_devices", {})]}, {"text": "Done."}]
    )
    adds = [i for i in ctx.of("item_add") if i["kind"] == "step"]
    updates = ctx.of("item_update")
    assert adds[0]["state"] == "running"
    assert updates[-1]["label"] == "Looked at 6 devices"
    assert updates[-1]["state"] == "done"
    # The model got the devices, compacted, with security marked.
    result = json.loads(tool_results(provider, 1)[0]["content"])
    assert {d["device_id"] for d in result if d.get("security")} == {"lock.front", "switch.gate"}


def test_show_devices_puts_a_card_on_screen():
    _out, ctx, *_ = run_turn(
        [
            {"tools": [("show_devices", {"title": "Still on",
                                         "device_ids": ["light.island", "light.lamp"]})]},
            {"text": "Want me to turn them off?"},
        ]
    )  # fmt: skip
    card = next(i for i in ctx.of("item_add") if i["kind"] == "devices")
    assert card["title"] == "Still on"
    assert [(r["room"], r["name"], r["state"]) for r in card["rows"]] == [
        ("Kitchen", "Island pendants", "On, 80%"),
        ("Living room", "Floor lamp", "On, 40%"),
    ]
    assert all(r["lit"] for r in card["rows"])


def test_suggestions_are_offered():
    _out, ctx, *_ = run_turn(
        [{"tools": [("suggest_replies", {"options": ["Dim it instead", " ", "Show it"]})]},
         {"text": "."}]
    )  # fmt: skip
    s = next(i for i in ctx.of("item_add") if i["kind"] == "suggestions")
    assert s["options"] == ["Dim it instead", "Show it"]


# ── confirm ─────────────────────────────────────────────────────────────────


def test_a_change_waits_for_yes_and_then_runs():
    _out, ctx, hc, provider, _ = run_turn(
        [{"tools": [OFF_THREE]}, {"text": "Done."}], answers=[{"choice": "go"}]
    )
    card = ctx.of("awaiting_user")[0]
    assert card["prompt"] == "Turn off 3 lights"
    data = card["data"]
    assert data["kind"] == "confirm"
    assert data["preview"]["detail"] == "Island pendants, Under cabinet, Floor lamp"
    assert [c["label"] for c in data["choices"]] == ["Not now", "Turn them off"]
    assert set(card["schema"]["properties"]["choice"]["enum"]) == {"go", "cancel"}
    assert [d for d, _ in hc.commands] == ["light.island", "light.cabinet", "light.lamp"]
    decided = next(i for i in ctx.of("item_add") if i["kind"] == "decided")
    assert decided["outcome"] == "done"
    assert decided["id"] == data["id"]
    assert tool_results(provider, 1)[0]["is_error"] is False


def test_not_now_changes_nothing_and_tells_the_model():
    _out, ctx, hc, provider, _ = run_turn(
        [{"tools": [OFF_THREE]}, {"text": "Okay, left them on."}],
        answers=[{"choice": "cancel"}],
    )
    assert hc.commands == []
    decided = next(i for i in ctx.of("item_add") if i["kind"] == "decided")
    assert decided["outcome"] == "declined"
    assert "chose not to" in tool_results(provider, 1)[0]["content"]


def test_typing_instead_of_answering_holds_the_change():
    _out, ctx, hc, _provider, _ = run_turn(
        [{"tools": [OFF_THREE]}, {"text": ""}],
        answers=[{"choice": "cancel", "reason": "replied"}],
    )
    assert hc.commands == []
    assert next(i for i in ctx.of("item_add") if i["kind"] == "decided")["outcome"] == "replied"


def test_an_unanswered_card_expires(monkeypatch):
    monkeypatch.setattr(chat_mod, "CONFIRM_TIMEOUT_SECS", 0)
    _out, ctx, hc, *_ = run_turn([{"tools": [OFF_THREE]}, {"text": "."}])
    assert hc.commands == []
    assert next(i for i in ctx.of("item_add") if i["kind"] == "decided")["outcome"] == "expired"


def test_with_ask_first_off_it_just_runs():
    _out, ctx, hc, *_ = run_turn(
        [{"tools": [OFF_THREE]}, {"text": "Done."}], settings=Settings(confirm=False)
    )
    assert ctx.of("awaiting_user") == []
    assert len(hc.commands) == 3


def test_a_draft_automation_is_saved_as_chosen():
    rule = {"name": "Porch light at the door", "trigger": {}, "conditions": [], "actions": []}
    explain = {"when": ["Front door opens"], "only_if": ["After sunset"],
               "do": ["Turn on Porch light"]}  # fmt: skip
    _out, ctx, hc, *_ = run_turn(
        [{"tools": [("create_rule", {"rule": rule, "explain": explain})]}, {"text": "Saved."}],
        answers=[{"choice": "save_off"}],
    )
    preview = ctx.of("awaiting_user")[0]["data"]["preview"]
    assert preview["type"] == "rule"
    assert preview["badge"] == "Not saved"
    assert preview["when"] == ["Front door opens"]
    choices = [c["id"] for c in ctx.of("awaiting_user")[0]["data"]["choices"]]
    assert choices == ["save_off", "save_on"]
    # Saved turned off, and without the words the model wrote for the card.
    assert hc.created == [{**rule, "enabled": False}]
    decided = next(i for i in ctx.of("item_add") if i["kind"] == "decided")
    assert decided["rule_id"] == "rule-new"


def test_a_draft_without_words_is_refused_before_anything():
    _out, ctx, hc, provider, _ = run_turn(
        [{"tools": [("create_rule", {"rule": {"name": "x"}})]}, {"text": "."}]
    )
    assert hc.created == []
    assert ctx.of("awaiting_user") == []
    result = tool_results(provider, 1)[0]
    assert result["is_error"] and "explain" in result["content"]


# ── security ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("device_id", ["lock.front", "switch.gate"])
def test_security_devices_are_refused_unless_allowed(device_id):
    _out, ctx, hc, provider, _ = run_turn(
        [{"tools": [("command_device", {"device_id": device_id, "command": {"on": True}})]},
         {"text": "I can't."}]
    )  # fmt: skip
    assert hc.commands == []
    assert ctx.of("awaiting_user") == []
    result = tool_results(provider, 1)[0]
    assert result["is_error"] and "Locks, doors and security" in result["content"]


def test_a_device_taken_out_of_security_is_not_gated():
    _out, _ctx, hc, *_ = run_turn(
        [{"tools": [("command_device", {"device_id": "sensor.pantry", "command": {"on": True}})]},
         {"text": "."}],
        answers=[{"choice": "go"}],
    )  # fmt: skip
    assert hc.commands == [("sensor.pantry", {"on": True})]


def test_security_allowed_still_asks_first():
    _out, ctx, hc, *_ = run_turn(
        [{"tools": [("command_device", {"device_id": "lock.front",
                                        "command": {"locked": True}})]},
         {"text": "Locked."}],
        settings=Settings(security=True),
        answers=[{"choice": "go"}],
    )  # fmt: skip
    assert ctx.of("awaiting_user")[0]["prompt"] == "Lock Front door lock"
    assert hc.commands == [("lock.front", {"locked": True})]


def test_a_bulk_command_with_one_lock_is_refused_whole():
    cmds = {"commands": [{"device_id": "light.lamp", "command": {"on": False}},
                         {"device_id": "lock.front", "command": {"locked": True}}]}  # fmt: skip
    _out, _ctx, hc, *_ = run_turn([{"tools": [("bulk_command", cmds)]}, {"text": "."}])
    assert hc.commands == []


def test_a_scene_that_locks_a_door_is_gated():
    _out, _ctx, hc, *_ = run_turn(
        [{"tools": [("run_scene", {"scene_id": "scene-lockup"})]}, {"text": "."}]
    )
    assert hc.commands == []


def test_an_automation_touching_a_lock_is_gated():
    rule = {"name": "Lock at night", "actions": [{"device_id": "lock.front"}]}
    _out, _ctx, hc, *_ = run_turn(
        [{"tools": [("create_rule", {"rule": rule, "explain": {"when": ["11 PM"],
                                                               "do": ["Lock it"]}})]},
         {"text": "."}]
    )  # fmt: skip
    assert hc.created == []


# ── who is asking ───────────────────────────────────────────────────────────


def test_tools_offered_follow_the_callers_scopes():
    _, _, _, provider, _ = run_turn([{"text": "."}], caller=MEMBER)
    names = {t["name"] for t in provider.requests[0]["tools"]}
    assert "command_device" in names and "run_scene" in names
    assert "create_rule" not in names
    assert "list_plugins" not in names  # members don't hold plugins:read
    assert "only an admin or a user account can" in provider.requests[0]["system"]


def test_a_read_only_account_only_reads():
    _, _, _, provider, _ = run_turn([{"text": "."}], caller=READ_ONLY)
    tools = provider.requests[0]["tools"]
    assert tools and all(
        t["name"]
        not in {"command_device", "bulk_command", "run_scene", "create_rule", "delete_rule"}
        for t in tools
    )


def test_a_tool_the_caller_lacks_is_refused_even_if_called():
    _out, _ctx, hc, provider, _ = run_turn(
        [{"tools": [("create_rule", {"rule": {}, "explain": {"when": [], "do": []}})]},
         {"text": "."}],
        caller=MEMBER,
    )  # fmt: skip
    assert hc.created == []
    assert tool_results(provider, 1)[0]["is_error"]


def test_switched_off_categories_are_not_offered():
    _, _, _, provider, _ = run_turn(
        [{"text": "."}], settings=Settings(device_commands=False, rule_mutations=False)
    )
    names = {t["name"] for t in provider.requests[0]["tools"]}
    assert not names & {"command_device", "bulk_command", "run_scene", "create_rule"}
    assert "turned off in the assistant's settings" in provider.requests[0]["system"]


def test_the_system_prompt_names_the_person_and_their_units():
    prompt = system_prompt(caller=MEMBER, tools=[], settings=Settings(), units="F")
    assert "sam (role: household member)" in prompt
    assert "°F" in prompt
    assert "—" not in prompt and "–" not in prompt


# ── failures ────────────────────────────────────────────────────────────────


def test_an_api_failure_leaves_the_conversation_as_it_was():
    chat = Chat(id=new_chat_id(), owner="o")
    out, _ctx, *_ = run_turn(
        [], provider=FakeProvider([], error=ProviderError("Claude is busy.", "busy")), chat=chat
    )
    assert out == {"error": "Claude is busy.", "reason": "busy"}
    assert chat.api_messages == []
    assert chat.turns[-1]["parts"][-1] == {
        "id": chat.turns[-1]["parts"][-1]["id"],
        "kind": "notice",
        "text": "Claude is busy.",
    }


def test_a_second_turn_carries_on_the_conversation():
    chat = Chat(id=new_chat_id(), owner="o")
    run_turn([{"text": "Hi."}], chat=chat, text="hello")
    _, _, _, provider, _ = run_turn([{"text": "Again."}], chat=chat, text="and again")
    sent = provider.requests[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert chat.title == "hello"


def test_command_preview_words():
    one = command_preview({"on": True}, [{"device_id": "a", "name": "Porch light"}])
    assert one == {"type": "devices", "title": "Turn on Porch light", "detail": "Porch light",
                   "button": "Turn it on"}  # fmt: skip
    mixed = command_preview(
        {"locked": False},
        [{"device_id": "a", "name": "A", "device_type": "lock"},
         {"device_id": "b", "name": "B", "device_type": "light"}],
    )  # fmt: skip
    assert mixed["title"] == "Unlock 2 devices" and mixed["button"] == "Unlock them"
