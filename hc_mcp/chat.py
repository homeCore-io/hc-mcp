"""One turn of the in-app chat: the person's message in, the reply out, as a
stream the chat screen draws while it is written.

The loop asks the model, runs the tools it calls (from the same registry the
MCP server serves), and asks again until the model is done. It never goes
beyond the person asking: the model sees only the tools the settings allow
and the person's scopes cover. A tool that changes something stops for the
person's say so first when "Ask before every change" is on, and a device that
counts for security needs "Locks, doors and security" as well.

What goes on the stream (all through the SDK's StreamContext; the full list,
with every field, is in docs/chat-events.md):

- ``progress`` with ``data.kind == "text"``: reply text as it is written;
- ``item`` add/update: a part of the reply, keyed by ``id``: a step chip
  (``step``), a device card (``devices``), tap replies (``suggestions``), what
  happened to a change (``decided``), a plain note (``notice``);
- ``awaiting_user`` with ``data.kind == "confirm"``: the confirm card;
- ``complete``: the whole reply as stored, so the screen can redraw it exactly;
- ``error``: in words for the person.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import jsonschema

from . import guides, registry, security
from .chats import Chat
from .provider import MAX_TOKENS, REFUSAL, Canceled, Provider, ProviderError, ToolCall
from .registry import ToolSpec
from .settings import Settings
from .tools import house

#: Rounds of tool calls in one reply before the loop gives up.
MAX_ROUNDS = 12
#: How long a confirm card waits for an answer.
CONFIRM_TIMEOUT_SECS = 10 * 60
#: A tool result longer than this is cut, with a note saying so.
MAX_RESULT_CHARS = 40_000
#: Text is sent in pieces at least this long, or this often.
TEXT_FLUSH_CHARS = 48
TEXT_FLUSH_SECS = 0.08

SECURITY_REFUSAL = (
    "Not done: {names} counts for security (locks, doors and the like), and the "
    "assistant isn't allowed to control those. An admin can allow it in "
    "Settings > Plugins > Assistant, under Locks, doors and security."
)

#: What the model writes for an automation, for the person to check.
EXPLAIN_SCHEMA = {
    "type": "object",
    "description": (
        "The automation in plain words, for the person to check before it is saved. "
        "One short line per item, using the names people use (rooms, device names), "
        "no ids or JSON."
    ),
    "properties": {
        "when": {"type": "array", "items": {"type": "string"}},
        "only_if": {"type": "array", "items": {"type": "string"}},
        "do": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["when", "do"],
}
EXPLAINED = {"create_rule", "update_rule"}


def chat_schema(spec: ToolSpec) -> dict:
    """A tool's input schema as the chat offers it."""
    schema = json.loads(json.dumps(spec.input_schema))
    if spec.name in EXPLAINED:
        schema["properties"]["explain"] = EXPLAIN_SCHEMA
        schema.setdefault("required", []).append("explain")
    return schema


def tool_defs(tools: list[ToolSpec]) -> list[dict]:
    return [
        {"name": t.name, "description": t.chat_description, "input_schema": chat_schema(t)}
        for t in tools
    ]


def title_from(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:57].rstrip() + "..."


def system_prompt(
    *,
    caller: dict,
    tools: list[ToolSpec],
    settings: Settings,
    units: str | None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now().astimezone()
    name = caller.get("username") or "someone"
    role = (caller.get("role") or "user").replace("_", " ")
    offered = {t.name for t in tools}
    cannot = []
    if "command_device" not in offered:
        cannot.append(
            "control devices or run scenes ("
            + (
                "not allowed for their account"
                if "devices:command" not in (caller.get("scopes") or [])
                else "turned off in the assistant's settings"
            )
            + ")"
        )
    if "create_rule" not in offered:
        cannot.append(
            "make or change automations ("
            + (
                "only an admin or a user account can"
                if "automations:write" not in (caller.get("scopes") or [])
                else "turned off in the assistant's settings"
            )
            + ")"
        )
    if not settings.security:
        cannot.append(
            "control devices that count for security, such as locks and doors "
            "(an admin can allow it in the assistant's settings)"
        )
    temp = (
        "They read temperatures in °F: say temperatures in °F, and convert °F they give you "
        "to °C for homeCore."
        if units == "F"
        else "They read temperatures in °C."
    )
    lines = [
        (
            "You are the assistant inside homeCore, a home automation system, chatting with "
            f"{name} (role: {role}) in the homeCore app."
        ),
        f"It is {now.strftime('%A, %B %-d, %Y, %-I:%M %p')} ({now.tzname()}) where homeCore runs.",
        "",
        (
            "homeCore's words: devices (lights, switches, sensors, locks, thermostats; each has a "
            "device_id, a name, a room and attributes), rooms (also called areas), automations "
            "(each has triggers that start it, conditions that must hold, and actions it takes), "
            "scenes (saved states for several devices), and modes (house-wide on/off states such "
            "as Away or Night)."
        ),
        (
            "Device attributes use one vocabulary: on, brightness_pct 0 to 100, color_temp in "
            "kelvin, locked, open, position 0 to 100 (100 is open), temperature and setpoints in "
            f"°C, battery_pct, motion. {temp}"
        ),
        "",
        "How to answer:",
        (
            "- Be brief and plain. Short sentences, everyday words, American spelling. No headings, "
            "no tables, no dashes as punctuation. Never show device ids, JSON or tool names."
        ),
        (
            "- Look things up with the tools rather than guessing; say so when you can't find "
            "something."
        ),
        "- To list devices, call show_devices instead of writing the list out.",
        "- When a short follow up is likely, end with suggest_replies (at most three).",
        (
            "- Before you make an automation, read one existing automation with get_rule to copy "
            "its exact shape, and fill in explain in plain words."
        ),
        (
            "- Anything that changes the house is shown to the person to confirm first when they "
            'have asked for that; just call the tool, and don\'t ask "shall I?" in text as well.'
        ),
        (
            "- If a tool says the person chose not to do something, accept it and don't try again "
            "unless they ask."
        ),
    ]
    if "read_skill" in offered and guides.skills():
        lines += [
            "",
            (
                "For how-to questions (installing or upgrading homeCore, settings, adding plugins, "
                "plugin runtimes or users, a development setup, writing a plugin), read the guide "
                "that covers it with read_skill before answering, and follow it. Name the screen "
                "in the app that does each step. Adding plugins, changing users and anything about "
                "security is for an admin: say so if the person isn't one. The guides:"
            ),
            *(f"- {s.name}: {s.description}" for s in guides.skills()),
        ]
    if cannot:
        lines += [
            "",
            f"{name} can't, through you: " + "; ".join(cannot) + ". If they ask, say so "
            "plainly and offer what you can do instead.",
        ]
    return "\n".join(lines)


# ── what a change will do, in words ──────────────────────────────────────────

_NOUNS = {
    "light": "lights",
    "switch": "switches",
    "lock": "locks",
    "fan": "fans",
    "cover": "covers",
    "thermostat": "thermostats",
    "climate": "thermostats",
    "outlet": "outlets",
}


def command_words(command: dict) -> tuple[str, str]:
    """What a device command does: the title's verb and the button, with
    ``{it}`` for "it" or "them"."""
    if "action" in command:
        return (f"Run {command['action']} on", "Do it")
    if command.get("on") is False:
        return ("Turn off", "Turn {it} off")
    if command.get("on") is True:
        return ("Turn on", "Turn {it} on")
    if command.get("locked") is True:
        return ("Lock", "Lock {it}")
    if command.get("locked") is False:
        return ("Unlock", "Unlock {it}")
    if command.get("position") == 100:
        return ("Open", "Open {it}")
    if command.get("position") == 0:
        return ("Close", "Close {it}")
    return ("Change", "Change {it}")


def command_preview(command: dict, devices: list[dict]) -> dict:
    verb, button = command_words(command)
    names = [house.device_label(d) for d in devices]
    if len(devices) == 1:
        title = f"{verb} {names[0]}"
    else:
        types = {d.get("device_type") for d in devices}
        noun = _NOUNS.get(types.pop(), "devices") if len(types) == 1 else "devices"
        title = f"{verb} {len(devices)} {noun}"
    return {
        "type": "devices",
        "title": title,
        "detail": ", ".join(names),
        "button": button.format(it="it" if len(devices) == 1 else "them"),
    }


# ── the stream ───────────────────────────────────────────────────────────────


class Stream:
    """Reports one reply to the chat screen and keeps the same parts for the
    stored chat. Wraps the SDK's StreamContext."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.parts: list[dict] = []
        self._text_part: dict | None = None
        self._pending = ""
        self._last_flush = 0.0

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    # text, as it is written

    def text(self, delta: str) -> None:
        if not delta:
            return
        if self._text_part is None:
            self._text_part = {"id": self.new_id(), "kind": "text", "text": ""}
            self.parts.append(self._text_part)
        self._text_part["text"] += delta
        self._pending += delta
        now = time.monotonic()
        if len(self._pending) >= TEXT_FLUSH_CHARS or now - self._last_flush >= TEXT_FLUSH_SECS:
            self.flush()

    def flush(self) -> None:
        if self._pending and self._text_part is not None:
            self.ctx.progress(
                data={"kind": "text", "part": self._text_part["id"], "delta": self._pending}
            )
        self._pending = ""
        self._last_flush = time.monotonic()

    def end_text(self) -> None:
        self.flush()
        self._text_part = None

    # parts

    def add(self, part: dict) -> dict:
        self.end_text()
        self.parts.append(part)
        self.ctx.item_add(part)
        return part

    def update(self, part: dict, **changes: Any) -> None:
        part.update(changes)
        self.ctx.item_update(part)

    def notice(self, text: str) -> None:
        self.add({"id": self.new_id(), "kind": "notice", "text": text})


@dataclass
class Decision:
    choice: str
    #: Why it was not a yes: "declined", "replied", "expired", "canceled".
    outcome: str = "done"


class Turn:
    """One reply to one message."""

    def __init__(
        self,
        *,
        ctx: Any,
        provider: Provider,
        settings: Settings,
        caller: dict,
        chat: Chat,
        units: str | None = None,
        save: Callable[[Chat], None] = lambda _c: None,
        key_scopes: list[str] | None = None,
    ) -> None:
        self.ctx = ctx
        self.provider = provider
        self.settings = settings
        self.caller = caller
        self.chat = chat
        self.units = units
        self.save = save
        self.stream = Stream(ctx)
        self.tools = registry.for_chat(
            scopes=caller.get("scopes") or [],
            role=caller.get("role"),
            enabled=settings.enabled_categories(),
            key_scopes=key_scopes,
        )
        self.by_name = {t.name: t for t in self.tools}
        self._security_ids: set[str] | None = None

    # ── the loop ──────────────────────────────────────────────────────────

    async def run(self, text: str) -> dict:
        chat = self.chat
        messages = chat.api_messages
        start = len(messages)
        if not chat.title:
            chat.title = title_from(text)
        chat.turns.append({"role": "user", "text": text})
        messages.append(self.provider.user_message(text))
        system = system_prompt(
            caller=self.caller, tools=self.tools, settings=self.settings, units=self.units
        )
        defs = tool_defs(self.tools)
        stopped: str | None = None

        try:
            for round_no in range(MAX_ROUNDS):
                try:
                    reply = await self.provider.reply(
                        system=system,
                        messages=messages,
                        tools=defs,
                        on_text=self.stream.text,
                        should_stop=self.ctx.is_canceled,
                    )
                except ProviderError as exc:
                    if round_no == 0:
                        # Nothing happened: leave the conversation as it was,
                        # so the next message is not answered twice.
                        del messages[start:]
                    self.stream.end_text()
                    self.stream.notice(str(exc))
                    self._finish()
                    return {"error": str(exc), "reason": exc.reason}
                self.stream.end_text()
                messages.append({"role": "assistant", "content": reply.content or _EMPTY})

                if reply.stop == REFUSAL:
                    self.stream.notice("Claude declined to answer that.")
                    break
                if not reply.tool_calls:
                    break
                if reply.stop == MAX_TOKENS:
                    messages.append(
                        self.provider.tool_results_message(
                            [
                                (c.id, "The reply was cut off; nothing ran.", True)
                                for c in reply.tool_calls
                            ]
                        )
                    )
                    self.stream.notice("The reply ran too long and was cut off. Nothing changed.")
                    break

                results = []
                for call in reply.tool_calls:
                    if self.ctx.is_canceled():
                        results.append((call.id, "Stopped by the person; nothing ran.", True))
                        continue
                    results.append(await self.call(call))
                messages.append(self.provider.tool_results_message(results))
                self.save(chat)
                if self.ctx.is_canceled():
                    raise Canceled()
            else:
                self.stream.notice("I stopped after too many steps. Try asking a smaller question.")
        except Canceled:
            stopped = "canceled"
            self.stream.end_text()
            # A reply cut short still leaves the conversation valid: an
            # assistant message is answered by its tool results above, or
            # was never added.
            if messages and messages[-1].get("role") == "user" and len(messages) == start + 1:
                del messages[start:]

        self._finish()
        out = {"chat_id": chat.id, "title": chat.title, "turn": chat.turns[-1]}
        if stopped:
            out["stopped"] = stopped
        return out

    def _finish(self) -> None:
        self.stream.end_text()
        self.chat.turns.append({"role": "assistant", "parts": self.stream.parts})
        self.save(self.chat)

    # ── one tool call ─────────────────────────────────────────────────────

    async def call(self, call: ToolCall) -> tuple[str, str, bool]:
        spec = self.by_name.get(call.name)
        if spec is None:
            return (call.id, f"{call.name} is not available here.", True)
        args = dict(call.input) if isinstance(call.input, dict) else None
        if args is None:
            return (call.id, "The input must be an object.", True)
        try:
            jsonschema.validate(args, chat_schema(spec))
        except jsonschema.ValidationError as exc:
            return (call.id, f"Invalid input: {exc.message}", True)
        explain = args.pop("explain", None)

        if spec.name == "show_devices":
            return await self._show_devices(call, args)
        if spec.name == "suggest_replies":
            result = await spec.fn(**args)
            if result["options"]:
                self.stream.add({"id": self.stream.new_id(), "kind": "suggestions", **result})
            return (call.id, "Shown to the person.", False)

        if not spec.mutates:
            return await self._run(call, spec, args)

        refusal = await self._security_refusal(spec, args)
        if refusal:
            return (call.id, refusal, True)
        if not self.settings.confirm:
            return await self._run(call, spec, args)

        preview, choices = await self._preview(spec, args, explain)
        decision = await self._confirm(preview, choices)
        decided = {
            "id": decision_id(preview),
            "kind": "decided",
            "title": preview["title"],
        }
        if decision.outcome != "done":
            self.stream.add({**decided, "outcome": decision.outcome})
            return (call.id, _DECLINED[decision.outcome], False)
        if decision.choice in ("save_on", "save_off") and isinstance(args.get("rule"), dict):
            args["rule"] = {**args["rule"], "enabled": decision.choice == "save_on"}
        try:
            result = await spec.fn(**args)
        except Exception as exc:  # noqa: BLE001 - told to the model and the person
            self.stream.add({**decided, "outcome": "failed", "text": _failure(exc)})
            return (call.id, f"It failed: {_failure(exc)}", True)
        part = {**decided, "outcome": "done", "text": spec.step(args, result) if spec.step else ""}
        rule_id = _rule_id(spec, args, result)
        if rule_id:
            part["rule_id"] = rule_id
        self.stream.add(part)
        return (call.id, _shape(spec.name, result), False)

    async def _run(self, call: ToolCall, spec: ToolSpec, args: dict) -> tuple[str, str, bool]:
        chip = self.stream.add(
            {"id": self.stream.new_id(), "kind": "step", "label": spec.running, "state": "running"}
        )
        try:
            result = await spec.fn(**args)
        except Exception as exc:  # noqa: BLE001
            self.stream.update(chip, state="failed", label="Couldn't look that up")
            return (call.id, f"It failed: {_failure(exc)}", True)
        self.stream.update(
            chip, state="done", label=spec.step(args, result) if spec.step else spec.running
        )
        return (call.id, _shape(spec.name, result), False)

    async def _show_devices(self, call: ToolCall, args: dict) -> tuple[str, str, bool]:
        try:
            card = await house.show_devices(**args)
        except Exception as exc:  # noqa: BLE001
            return (call.id, f"It failed: {_failure(exc)}", True)
        if card["rows"]:
            self.stream.add(
                {
                    "id": self.stream.new_id(),
                    "kind": "devices",
                    "title": card["title"],
                    "rows": card["rows"],
                }
            )
        note = "Shown to the person."
        if card["missing"]:
            note += f" Not found: {', '.join(card['missing'])}."
        return (call.id, note, False)

    # ── security ──────────────────────────────────────────────────────────

    async def _security_refusal(self, spec: ToolSpec, args: dict) -> str | None:
        """Words refusing *spec* when it would touch a security device and
        that is not allowed; ``None`` when it may go ahead."""
        if self.settings.security:
            return None
        names = await security.touched(spec.name, args)
        if names:
            return SECURITY_REFUSAL.format(names=", ".join(names))
        return None

    # ── confirm ───────────────────────────────────────────────────────────

    async def _preview(
        self, spec: ToolSpec, args: dict, explain: dict | None
    ) -> tuple[dict, list[dict]]:
        from .server_state import client

        cancel = {"id": "cancel", "label": "Not now"}
        if spec.name in ("command_device", "bulk_command"):
            if spec.name == "command_device":
                ids, command = [args["device_id"]], args["command"]
            else:
                entries = args.get("commands", [])
                ids = [e.get("device_id") for e in entries]
                command = entries[0].get("command", {}) if entries else {}
            by_id = {d.get("device_id"): d for d in await client().list_devices()}
            devices = [by_id.get(i) or {"device_id": i, "name": i} for i in ids]
            preview = command_preview(command, devices)
            button = preview.pop("button")
            return preview, [cancel, {"id": "go", "label": button, "primary": True}]
        if spec.name == "run_scene":
            scenes = await client().list_scenes()
            scene = next((s for s in scenes if s.get("id") == args["scene_id"]), {})
            title = f"Run {scene.get('name') or 'the scene'}"
            return (
                {"type": "plain", "title": title},
                [cancel, {"id": "go", "label": "Run it", "primary": True}],
            )
        if spec.name in ("create_rule", "update_rule"):
            rule = args.get("rule") or {}
            explain = explain or {}
            preview = {
                "type": "rule",
                "title": rule.get("name") or "New automation",
                "badge": "Not saved",
                "when": explain.get("when", []),
                "only_if": explain.get("only_if", []),
                "do": explain.get("do", []),
                "rule": rule,
            }
            if spec.name == "update_rule":
                preview["badge"] = "Changes not saved"
                return preview, [cancel, {"id": "go", "label": "Save changes", "primary": True}]
            return preview, [
                {"id": "save_off", "label": "Save, turned off"},
                {"id": "save_on", "label": "Save and turn on", "primary": True},
            ]
        if spec.name in ("delete_rule", "enable_rule", "disable_rule"):
            try:
                rule = await client().get_automation(args["rule_id"])
            except httpx.HTTPError:
                rule = {}
            name = rule.get("name") or "the automation"
            verb, button, danger = {
                "delete_rule": ("Delete", "Delete it", True),
                "enable_rule": ("Turn on", "Turn it on", False),
                "disable_rule": ("Turn off", "Turn it off", False),
            }[spec.name]
            go = {"id": "go", "label": button, "primary": True}
            if danger:
                go["danger"] = True
            return {"type": "plain", "title": f"{verb} {name}"}, [cancel, go]
        plain = {
            "acknowledge_alert": ("Acknowledge the alert", "Acknowledge"),
            "resume_rule": ("Resume the paused automation", "Resume it"),
            "room_lights": (
                f"Turn the room's lights {'on' if args.get('on') else 'off'}",
                "Do it",
            ),
            "plugin_control": (
                f"{str(args.get('op', 'restart')).capitalize()} {args.get('plugin_id', 'the plugin')}",
                str(args.get("op", "restart")).capitalize(),
            ),
            "set_plugin_log_level": (
                f"Set {args.get('plugin_id', 'the plugin')}'s log level to {args.get('level')}",
                "Set it",
            ),
        }
        if spec.name in plain:
            title, label = plain[spec.name]
            return {"type": "plain", "title": title}, [
                cancel,
                {"id": "go", "label": label, "primary": True},
            ]
        # Another plugin's action.
        title = f"Run {args.get('action', 'an action')} on {args.get('plugin_id', 'a plugin')}"
        return (
            {"type": "plain", "title": title, "detail": json.dumps(args.get("params") or {})},
            [cancel, {"id": "go", "label": "Run it", "primary": True}],
        )

    async def _confirm(self, preview: dict, choices: list[dict]) -> Decision:
        """Show the confirm card and wait for the person."""
        self.stream.end_text()
        card_id = self.stream.new_id()
        preview["id"] = card_id
        ids = [c["id"] for c in choices] + ["cancel"]
        self.ctx.awaiting_user(
            preview["title"],
            {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": sorted(set(ids))},
                    "reason": {"type": "string"},
                },
                "required": ["choice"],
            },
            data={"kind": "confirm", "id": card_id, "preview": preview, "choices": choices},
        )
        deadline = time.monotonic() + CONFIRM_TIMEOUT_SECS
        while True:
            if self.ctx.is_canceled():
                return Decision("cancel", "canceled")
            if time.monotonic() > deadline:
                return Decision("cancel", "expired")
            try:
                answer = await asyncio.to_thread(self.ctx.await_respond, 1.0)
            except TimeoutError:
                continue
            choice = answer.get("choice") if isinstance(answer, dict) else None
            if choice not in ids:
                continue
            if choice == "cancel":
                reason = answer.get("reason")
                return Decision("cancel", "replied" if reason == "replied" else "declined")
            return Decision(choice)


_EMPTY = [{"type": "text", "text": "(no reply)"}]

_DECLINED = {
    "declined": "The person chose not to do this. Accept it, say so in a few words, and "
    "don't try again unless they ask.",
    "replied": "The person wants changes first; their next message says what. Don't do it "
    "now, and don't write anything more in this reply.",
    "expired": "Nobody answered the confirm card, so nothing was done.",
    "canceled": "The person stopped the reply; nothing was done.",
}


def decision_id(preview: dict) -> str:
    return preview.get("id") or uuid.uuid4().hex[:12]


def _failure(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        body = (exc.response.text or "").strip()
        return f"homeCore said {exc.response.status_code}" + (f": {body[:300]}" if body else "")
    if isinstance(exc, httpx.HTTPError):
        return "homeCore didn't answer"
    return str(exc) or type(exc).__name__


def _rule_id(spec: ToolSpec, args: dict, result: Any) -> str | None:
    if spec.name == "create_rule" and isinstance(result, dict):
        return result.get("id")
    if spec.name in ("update_rule", "enable_rule", "disable_rule"):
        return args.get("rule_id")
    return None


def _compact_device(d: dict) -> dict:
    out = {
        "device_id": d.get("device_id"),
        "name": house.device_label(d),
        "room": house.device_room(d),
        "type": d.get("device_type"),
        "available": d.get("available"),
        "attributes": {
            k: v
            for k, v in (d.get("attributes") or {}).items()
            if not isinstance(v, dict | list) or len(json.dumps(v)) < 200
        },
    }
    if house.is_security(d):
        out["security"] = True
    return out


def _shape(name: str, result: Any) -> str:
    """A tool's result as the model reads it: compact, and cut when long."""
    if name == "list_devices" and isinstance(result, list):
        result = [_compact_device(d) for d in result if isinstance(d, dict)]
    text = json.dumps(result, default=str, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " ... (cut short; ask for less, e.g. one device)"
    return text
