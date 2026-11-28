"""Async REST client for the homeCore API.

A thin wrapper around ``httpx.AsyncClient`` that pins the API base URL,
attaches ``Authorization: Bearer <api-key>`` to every request, and
returns parsed JSON. Tools call methods here rather than touching httpx
directly so retry / error policy stays in one place.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .config import Config


def seg(value: Any) -> str:
    """*value* as one path segment. An id is put in a path, and httpx
    resolves what it holds: `lamp/../lock` reached the lock, and `lock?`
    another endpoint, past the security check, which saw no such device.
    Slashes, `?` and `#` are encoded; `.` and `..` are refused."""
    s = str(value)
    if s in ("", ".", ".."):
        raise ValueError(f"hc-mcp: not done. {s!r} isn't an id.")
    return quote(s, safe="")


class HomeCoreClient:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=f"{cfg.base_url}/api/v1",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=cfg.timeout_secs,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Generic GET helper ─────────────────────────────────────────────────
    async def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        resp = await self._client.get(path, params=clean)
        resp.raise_for_status()
        return resp.json()

    async def send(self, method: str, path: str, body: dict | None = None) -> Any:
        """Any other call: *method* on *path*, JSON *body*. Returns the JSON
        reply, or ``{"ok": true}`` for an empty one. Raises on 4xx/5xx."""
        resp = await self._client.request(method, path, json=body)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True}
        return resp.json()

    # ── Endpoint-specific helpers ──────────────────────────────────────────
    async def system_status(self) -> dict:
        return await self.get("/system/status")

    async def list_plugins(self) -> list[dict]:
        return await self.get("/plugins")

    async def get_plugin(self, plugin_id: str) -> dict:
        return await self.get(f"/plugins/{seg(plugin_id)}")

    async def get_plugin_capabilities(self, plugin_id: str) -> dict:
        return await self.get(f"/plugins/{seg(plugin_id)}/capabilities")

    async def list_devices(self) -> list[dict]:
        return await self.get("/devices")

    async def get_device(self, device_id: str) -> dict:
        return await self.get(f"/devices/{seg(device_id)}")

    async def get_device_schema(self, device_id: str) -> dict | None:
        """GET /devices/{id}/schema, or ``None`` when the device declares none."""
        resp = await self._client.get(f"/devices/{seg(device_id)}/schema")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def device_history(
        self,
        device_id: str,
        attribute: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return await self.get(
            f"/devices/{seg(device_id)}/history",
            attribute=attribute,
            **{"from": from_},
            to=to,
            limit=limit,
        )

    async def list_automations(self) -> list[dict]:
        return await self.get("/automations")

    async def get_automation(self, rule_id: str) -> dict:
        return await self.get(f"/automations/{seg(rule_id)}")

    async def automation_history(self, rule_id: str, limit: int | None = None) -> list[dict]:
        return await self.get(f"/automations/{seg(rule_id)}/history", limit=limit)

    async def list_scenes(self) -> list[dict]:
        return await self.get("/scenes")

    async def list_rotations(self) -> list[dict]:
        """GET /rotations (homeCore 0.1.130): each with what plays now."""
        return await self.get("/rotations")

    async def play_rotation(self, rotation_id: str, device_id: str | None = None) -> dict:
        """POST /rotations/{id}/play: play its choice for now."""
        body = {"device_id": device_id} if device_id else None
        return await self.send("POST", f"/rotations/{seg(rotation_id)}/play", body)

    async def advance_rotation(self, rotation_id: str) -> dict:
        """POST /rotations/{id}/advance: move it on without playing."""
        return await self.send("POST", f"/rotations/{seg(rotation_id)}/advance")

    async def list_areas(self) -> list[dict]:
        return await self.get("/areas")

    async def activate_scene(self, scene_id: str) -> dict:
        """POST /scenes/{id}/activate: run a scene."""
        resp = await self._client.post(f"/scenes/{seg(scene_id)}/activate")
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "scene_id": scene_id}
        return resp.json()

    async def list_events(
        self,
        limit: int = 50,
        event_type: str | None = None,
        device_id: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if event_type:
            params["type"] = event_type
        if device_id:
            params["device_id"] = device_id
        return await self.get("/events", **params)

    async def test_automation(self, rule_id: str, at: str | None = None) -> dict:
        """POST /automations/{id}/test — dry-run the rule and report
        which conditions would pass and which actions would fire.
        ``at`` (RFC 3339) evaluates time conditions as of that moment.
        """
        params = {"at": at} if at else None
        resp = await self._client.post(f"/automations/{seg(rule_id)}/test", params=params)
        resp.raise_for_status()
        return resp.json()

    async def test_draft_automation(self, rule: dict, at: str | None = None) -> dict:
        """POST /automations/test — dry-run a rule that isn't saved."""
        params = {"at": at} if at else None
        resp = await self._client.post("/automations/test", json=rule, params=params)
        resp.raise_for_status()
        return resp.json()

    async def logs(
        self,
        level: str | None = None,
        plugin_id: str | None = None,
        target: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """GET /logs: the newest matching lines of homeCore's log ring,
        oldest first, as ``{count, lines}``. ``level`` is a minimum;
        ``plugin_id`` is exact (that plugin's process only); ``target`` a
        module prefix; ``since`` an RFC 3339 time. Admins only."""
        return await self.get(
            "/logs",
            level=level,
            plugin_id=plugin_id,
            target=target,
            since=since,
            limit=limit,
        )

    # ── Writes ─────────────────────────────────────────────────────────────
    async def send_plugin_command(
        self,
        plugin_id: str,
        action: str,
        params: dict | None = None,
    ) -> dict:
        body: dict = dict(params or {})
        body["action"] = action
        resp = await self._client.post(f"/plugins/{seg(plugin_id)}/command", json=body)
        resp.raise_for_status()
        return resp.json()

    async def query_plugin(
        self,
        plugin_id: str,
        action: str,
        params: dict | None = None,
    ) -> dict:
        """POST /plugins/{id}/query: a read-only action, open to anyone who
        can read devices (``/command`` needs ``plugins:write``)."""
        body: dict = dict(params or {})
        body["action"] = action
        resp = await self._client.post(f"/plugins/{seg(plugin_id)}/query", json=body)
        resp.raise_for_status()
        return resp.json()

    async def command_device(self, device_id: str, command: dict) -> dict:
        """PATCH /devices/{id}/state — issue a command to a device.

        Body is an attribute write (`{"<attr>": <value>, ...}`) or a
        declared action (`{"action": "<name>", ...params}`). The device's
        schema lists its writable attributes and actions.
        """
        resp = await self._client.patch(f"/devices/{seg(device_id)}/state", json=command)
        resp.raise_for_status()
        # Some core paths return 204 No Content on success.
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "device_id": device_id}
        return resp.json()

    async def enable_automation(self, rule_id: str) -> dict:
        return await self._patch_automation(rule_id, {"enabled": True})

    async def disable_automation(self, rule_id: str) -> dict:
        return await self._patch_automation(rule_id, {"enabled": False})

    async def set_automation_priority(self, rule_id: str, priority: int) -> dict:
        return await self._patch_automation(rule_id, {"priority": priority})

    async def _patch_automation(self, rule_id: str, patch: dict) -> dict:
        resp = await self._client.patch(f"/automations/{seg(rule_id)}", json=patch)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "rule_id": rule_id, "patch": patch}
        return resp.json()

    async def delete_automation(self, rule_id: str) -> dict:
        """DELETE /automations/{id} — removes the rule file. Core answers
        204 with no body."""
        resp = await self._client.delete(f"/automations/{seg(rule_id)}")
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "rule_id": rule_id}
        return resp.json()

    async def create_automation(self, rule: dict) -> dict:
        """POST /automations — create a new rule. Body shape per the
        Rule struct in CLAUDE.md (trigger / conditions / actions).
        """
        resp = await self._client.post("/automations", json=rule)
        resp.raise_for_status()
        return resp.json()

    async def update_automation(self, rule_id: str, rule: dict) -> dict:
        """PUT /automations/{id} — full replace of the rule body."""
        resp = await self._client.put(f"/automations/{seg(rule_id)}", json=rule)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "rule_id": rule_id}
        return resp.json()

    async def stream_plugin_command(
        self,
        plugin_id: str,
        request_id: str,
        timeout_secs: float,
    ):
        """Async generator over a streaming-action's SSE events.

        Each yielded value is the parsed JSON object from one ``data:``
        line (one event per stage emission). The generator returns
        when the connection closes — typically right after the SSE
        handler emits a terminal-stage event, since the core closes
        the stream on that boundary.

        Caller is responsible for breaking out of the iteration on
        terminal stages (``complete | error | canceled | timeout``);
        otherwise an unbounded action would block forever. The
        ``timeout_secs`` argument bounds the underlying read so a
        broken plugin can't hang the MCP tool.
        """
        import json

        path = f"/plugins/{seg(plugin_id)}/command/{seg(request_id)}/stream"
        async with self._client.stream("GET", path, timeout=timeout_secs) as resp:
            resp.raise_for_status()
            data_buf: list[str] = []
            async for raw_line in resp.aiter_lines():
                line = raw_line.rstrip("\r")
                if line == "":
                    if data_buf:
                        try:
                            yield json.loads("\n".join(data_buf))
                        except json.JSONDecodeError:
                            pass
                        data_buf = []
                    continue
                if line.startswith(":"):
                    # SSE comment / keep-alive; ignore.
                    continue
                if line.startswith("data:"):
                    data_buf.append(line[5:].lstrip())
                # `event:` and `id:` lines are ignored — every event
                # the core emits has the same `event: stream` type.
