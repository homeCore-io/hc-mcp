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

    async def list_events(self, limit: int = 50) -> list[dict]:
        return await self.get("/events", limit=limit)

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
