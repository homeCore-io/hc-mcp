"""Async REST client for the homeCore API.

A thin wrapper around ``httpx.AsyncClient`` that pins the API base URL,
attaches ``Authorization: Bearer <api-key>`` to every request, and
returns parsed JSON. Tools call methods here rather than touching httpx
directly so retry / error policy stays in one place.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Config


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

    # ── Endpoint-specific helpers ──────────────────────────────────────────
    async def system_status(self) -> dict:
        return await self.get("/system/status")

    async def list_plugins(self) -> list[dict]:
        return await self.get("/plugins")

    async def get_plugin(self, plugin_id: str) -> dict:
        return await self.get(f"/plugins/{plugin_id}")

    async def get_plugin_capabilities(self, plugin_id: str) -> dict:
        return await self.get(f"/plugins/{plugin_id}/capabilities")

    async def list_devices(self) -> list[dict]:
        return await self.get("/devices")

    async def get_device(self, device_id: str) -> dict:
        return await self.get(f"/devices/{device_id}")

    async def device_history(
        self,
        device_id: str,
        attribute: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return await self.get(
            f"/devices/{device_id}/history",
            attribute=attribute,
            **{"from": from_},
            to=to,
            limit=limit,
        )

    async def list_automations(self) -> list[dict]:
        return await self.get("/automations")

    async def get_automation(self, rule_id: str) -> dict:
        return await self.get(f"/automations/{rule_id}")

    async def automation_history(self, rule_id: str, limit: int | None = None) -> list[dict]:
        return await self.get(f"/automations/{rule_id}/history", limit=limit)

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

    async def test_automation(self, rule_id: str) -> dict:
        """POST /automations/{id}/test — dry-run the rule and report
        which conditions would pass and which actions would fire.
        """
        resp = await self._client.post(f"/automations/{rule_id}/test")
        resp.raise_for_status()
        return resp.json()

    async def stream_logs(
        self,
        max_lines: int,
        timeout_secs: float,
        level: str | None = None,
        module: str | None = None,
        grep: str | None = None,
    ) -> list[dict]:
        """Connect to WS /logs/stream, accumulate up to max_lines that
        match the filters, then close. Bounded by timeout_secs.

        Returns a list of log records (dicts as emitted by hc-core).
        Filters applied client-side because the WS protocol may not
        accept all of them as query params today.
        """
        import asyncio
        import json
        import re

        from urllib.parse import urlparse, urlunparse

        # Build the WS URL by swapping http(s) → ws(s) on the configured base.
        parsed = urlparse(self._cfg.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = urlunparse((
            ws_scheme,
            parsed.netloc,
            parsed.path.rstrip("/") + "/api/v1/logs/stream",
            "",
            "",
            "",
        ))

        try:
            import websockets
        except ImportError as e:
            raise RuntimeError(
                "websockets package required for log streaming; "
                "install hc-mcp with [websockets] extra"
            ) from e

        headers = {"Authorization": f"Bearer {self._cfg.api_key}"}
        grep_re = re.compile(grep) if grep else None
        out: list[dict] = []

        async def collect() -> None:
            async with websockets.connect(ws_url, extra_headers=headers) as ws:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if level and rec.get("level", "").lower() != level.lower():
                        continue
                    if module and rec.get("module", "") != module:
                        continue
                    if grep_re and not grep_re.search(rec.get("message", "")):
                        continue
                    out.append(rec)
                    if len(out) >= max_lines:
                        return

        try:
            await asyncio.wait_for(collect(), timeout=timeout_secs)
        except asyncio.TimeoutError:
            pass  # return whatever we accumulated
        return out

    # ── Writes ─────────────────────────────────────────────────────────────
    async def send_plugin_command(
        self,
        plugin_id: str,
        action: str,
        params: dict | None = None,
    ) -> dict:
        body: dict = dict(params or {})
        body["action"] = action
        resp = await self._client.post(f"/plugins/{plugin_id}/command", json=body)
        resp.raise_for_status()
        return resp.json()

    async def command_device(self, device_id: str, command: dict) -> dict:
        """PATCH /devices/{id}/state — issue a command to a device.

        Body shape is plugin-specific; typically `{"action": "set",
        "<attr>": <value>, ...}`. The plugin's capability schema lists
        valid attributes for each device.
        """
        resp = await self._client.patch(
            f"/devices/{device_id}/state", json=command
        )
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
        resp = await self._client.patch(f"/automations/{rule_id}", json=patch)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "rule_id": rule_id, "patch": patch}
        return resp.json()

    async def delete_automation(self, rule_id: str) -> dict:
        """DELETE /automations/{id} — removes the rule and patches any
        rule files that reference its devices. Core returns
        ``{affected_rules: [...]}`` per CLAUDE.md."""
        resp = await self._client.delete(f"/automations/{rule_id}")
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"ok": True, "rule_id": rule_id, "affected_rules": []}
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
        resp = await self._client.put(f"/automations/{rule_id}", json=rule)
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

        path = f"/plugins/{plugin_id}/command/{request_id}/stream"
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
