"""Stand-ins for homeCore, the model and the plugin's stream. No network."""

from __future__ import annotations

import queue
from dataclasses import dataclass, field

import httpx

from hc_mcp.provider import END, TOOL_USE, Canceled, Reply, ToolCall

ADMIN = {
    "uid": "11111111-1111-4111-8111-111111111111",
    "username": "john",
    "role": "admin",
    "scopes": [
        "devices:read",
        "automations:read",
        "scenes:read",
        "areas:read",
        "devices:write",
        "devices:command",
        "scenes:run",
        "automations:write",
        "scenes:write",
        "plugins:read",
        "plugins:write",
        "audit:read",
        "users:write",
    ],
    "kind": "user",
}
MEMBER = {
    "uid": "22222222-2222-4222-8222-222222222222",
    "username": "sam",
    "role": "household_member",
    "scopes": [
        "devices:read",
        "automations:read",
        "scenes:read",
        "areas:read",
        "devices:command",
        "scenes:run",
    ],
    "kind": "user",
}
READ_ONLY = {
    "uid": "33333333-3333-4333-8333-333333333333",
    "username": "guest",
    "role": "read_only",
    "scopes": ["devices:read", "automations:read", "scenes:read", "areas:read"],
    "kind": "user",
}


def light(device_id: str, name: str, room: str, on: bool, level: int | None = None) -> dict:
    attrs: dict = {"on": on}
    if level is not None:
        attrs["brightness_pct"] = level
    return {
        "device_id": device_id,
        "name": name,
        "area": room,
        "device_type": "light",
        "available": True,
        "attributes": attrs,
    }


def house() -> list[dict]:
    return [
        light("light.island", "Island pendants", "Kitchen", True, 80),
        light("light.cabinet", "Under cabinet", "Kitchen", True),
        light("light.lamp", "Floor lamp", "Living room", True, 40),
        {
            "device_id": "lock.front",
            "name": "Front door lock",
            "area": "Entry",
            "device_type": "lock",
            "available": True,
            "attributes": {"locked": False},
        },
        {
            # Not a lock by type, but marked Security by an admin.
            "device_id": "switch.gate",
            "name": "Gate opener",
            "area": "Garage",
            "device_type": "switch",
            "security": True,
            "available": True,
            "attributes": {"on": False},
        },
        {
            # A door sensor taken out of security by an admin.
            "device_id": "sensor.pantry",
            "name": "Pantry door",
            "area": "Kitchen",
            "device_type": "contact_sensor",
            "security": False,
            "available": True,
            "attributes": {"open": False},
        },
    ]


class FakeHomeCore:
    """The handful of homeCore calls the chat makes, recorded."""

    def __init__(self, devices: list[dict] | None = None) -> None:
        self.devices = devices if devices is not None else house()
        self.commands: list[tuple[str, dict]] = []
        self.created: list[dict] = []
        self.scenes = [
            {"id": "scene-night", "name": "Night", "states": {"light.lamp": {"on": False}}},
            {"id": "scene-lockup", "name": "Lock up", "states": {"lock.front": {"locked": True}}},
        ]
        self.rules = {
            "rule-1": {"id": "rule-1", "name": "Good night", "enabled": True,
                       "actions": [{"SetDeviceState": {"device_id": "light.lamp"}}]},
        }  # fmt: skip
        self.closed = False

    async def list_devices(self) -> list[dict]:
        return self.devices

    async def get_device(self, device_id: str) -> dict:
        for d in self.devices:
            if d["device_id"] == device_id:
                return d
        request = httpx.Request("GET", f"http://hc/api/v1/devices/{device_id}")
        raise httpx.HTTPStatusError(
            "404", request=request, response=httpx.Response(404, request=request)
        )

    async def command_device(self, device_id: str, command: dict) -> dict:
        self.commands.append((device_id, command))
        return {"ok": True, "device_id": device_id}

    async def list_scenes(self) -> list[dict]:
        return self.scenes

    async def activate_scene(self, scene_id: str) -> dict:
        self.commands.append((scene_id, {"action": "activate"}))
        return {"ok": True}

    async def list_areas(self) -> list[dict]:
        return [{"id": "a1", "name": "Kitchen"}]

    async def list_automations(self) -> list[dict]:
        return list(self.rules.values())

    async def get_automation(self, rule_id: str) -> dict:
        return self.rules[rule_id]

    async def create_automation(self, rule: dict) -> dict:
        self.created.append(rule)
        return {**rule, "id": "rule-new"}

    async def disable_automation(self, rule_id: str) -> dict:
        self.commands.append((rule_id, {"enabled": False}))
        return {"ok": True}

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Event:
    stage: str
    body: dict


@dataclass
class FakeCtx:
    """The SDK's StreamContext, keeping what was emitted."""

    caller: dict | None = None
    request_id: str = "req-1"
    events: list[Event] = field(default_factory=list)
    answers: queue.Queue = field(default_factory=queue.Queue)
    canceled_flag: bool = False

    def progress(self, *, percent=None, label=None, message=None, data=None) -> None:
        self.events.append(Event("progress", {"data": data, "message": message}))

    def item_add(self, data: dict) -> None:
        self.events.append(Event("item_add", dict(data)))

    def item_update(self, data: dict) -> None:
        self.events.append(Event("item_update", dict(data)))

    def warning(self, message: str, data: dict | None = None) -> None:
        self.events.append(Event("warning", {"message": message}))

    def awaiting_user(self, prompt, response_schema=None, data=None) -> None:
        self.events.append(
            Event("awaiting_user", {"prompt": prompt, "schema": response_schema, "data": data})
        )

    def await_respond(self, timeout: float | None = None) -> dict:
        try:
            return self.answers.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError() from exc

    def is_canceled(self) -> bool:
        return self.canceled_flag

    def complete(self, data: dict | None = None) -> None:
        self.events.append(Event("complete", data or {}))

    def error(self, message: str) -> None:
        self.events.append(Event("error", {"message": message}))

    def canceled(self) -> None:
        self.events.append(Event("canceled", {}))

    # helpers for tests

    def stages(self) -> list[str]:
        return [e.stage for e in self.events]

    def of(self, stage: str) -> list[dict]:
        return [e.body for e in self.events if e.stage == stage]

    def text(self) -> str:
        return "".join(
            (e.body.get("data") or {}).get("delta", "")
            for e in self.events
            if e.stage == "progress"
        )


class FakeProvider:
    """Plays back scripted replies; each is text and tool calls."""

    def __init__(self, script: list[dict], error: Exception | None = None) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        self.error = error

    def user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def tool_results_message(self, results):
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": t, "content": c, "is_error": e}
                for t, c, e in results
            ],
        }

    async def reply(self, *, system, messages, tools, on_text, should_stop) -> Reply:
        self.requests.append(
            {"system": system, "messages": [dict(m) for m in messages], "tools": tools}
        )
        if self.error is not None:
            raise self.error
        if should_stop():
            raise Canceled()
        step = self.script.pop(0)
        content: list[dict] = []
        if step.get("text"):
            for piece in step["text"].split(" "):
                on_text(piece + " ")
            content.append({"type": "text", "text": step["text"]})
        calls = []
        for i, (name, args) in enumerate(step.get("tools", [])):
            call_id = f"toolu_{len(self.requests)}_{i}"
            calls.append(ToolCall(id=call_id, name=name, input=args))
            content.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
        return Reply(content=content, stop=TOOL_USE if calls else END, tool_calls=calls)

    async def check(self) -> None:
        if self.error is not None:
            raise self.error
