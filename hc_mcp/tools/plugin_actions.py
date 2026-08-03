"""Plugin-capability action tools (Phase 4).

Three tools:

- ``list_plugin_actions``: discovery — flattens every plugin's capability
  manifest into one list. Always available (read-only).
- ``invoke_plugin_action``: dispatcher — POSTs a non-streaming action
  command. Write-gated behind ``HC_MCP_ALLOW_WRITE=plugin_actions``
  (also satisfied by ``HC_MCP_ALLOW_WRITE=all``).
- ``await_streaming_plugin_action`` (Phase 4b): POSTs a streaming
  action and reads the SSE stream until a terminal stage, returning
  an aggregated summary. Same write-gate.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from mcp.server.fastmcp import FastMCP

from ..permissions import ensure_write
from ..server_state import client

WRITE_CATEGORY = "plugin_actions"

TERMINAL_STAGES = {"complete", "error", "canceled", "timeout"}
DEFAULT_AWAIT_TIMEOUT_SECS = 90.0
MAX_AWAIT_TIMEOUT_SECS = 600.0


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_plugin_actions() -> list[dict]:
        """Every plugin-declared action across the system, flattened.

        Returns a list of ``{plugin_id, action_id, label, description,
        params, requires_role, stream, cancelable, timeout_ms}`` rows.
        Use this BEFORE ``invoke_plugin_action`` to learn which actions
        exist and what params each accepts.

        Plugins that haven't published a manifest are silently skipped."""
        c = client()
        plugins = await c.list_plugins()
        out: list[dict] = []
        for p in plugins:
            caps = p.get("capabilities")
            # Some plugins don't ship capabilities; skip rather than fail.
            if not caps:
                try:
                    caps = await c.get_plugin_capabilities(p["plugin_id"])
                except httpx.HTTPStatusError:
                    continue
            for action in caps.get("actions", []):
                out.append(
                    {
                        "plugin_id": p["plugin_id"],
                        "action_id": action.get("id"),
                        "label": action.get("label"),
                        "description": action.get("description"),
                        "params": action.get("params"),
                        "requires_role": action.get("requires_role", "user"),
                        "stream": action.get("stream", False),
                        "cancelable": action.get("cancelable", False),
                        "timeout_ms": action.get("timeout_ms"),
                    }
                )
        return out

    @mcp.tool()
    async def invoke_plugin_action(
        plugin_id: str,
        action: str,
        params: dict | None = None,
    ) -> dict:
        """Invoke a non-streaming plugin action.

        ``plugin_id`` and ``action`` come from ``list_plugin_actions``.
        ``params`` is a dict matching the action's params schema (or
        omit/empty for actions with no params).

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=plugin_actions`` (or
        ``all``) in the hc-mcp environment.

        Streaming actions are not supported here — they return a
        ``request_id`` and emit events asynchronously, which doesn't
        round-trip cleanly through a single MCP tool call. If you ask
        for a streaming action this tool returns an error explaining
        that. (Phase 4b will add a stream-aware variant that awaits the
        terminal stage.)"""
        ensure_write(WRITE_CATEGORY)
        c = client()

        # Resolve the action against the plugin's manifest so we can
        # short-circuit streaming actions cleanly.
        try:
            caps = await c.get_plugin_capabilities(plugin_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' has not published a capability manifest"
                ) from e
            raise
        match = next(
            (a for a in caps.get("actions", []) if a.get("id") == action),
            None,
        )
        if match is None:
            raise RuntimeError(
                f"Action '{action}' not declared by plugin '{plugin_id}'. "
                f"Use list_plugin_actions to see available actions."
            )
        if match.get("stream"):
            raise RuntimeError(
                f"Action '{action}' on plugin '{plugin_id}' is a streaming "
                f"action. Use `await_streaming_plugin_action` instead — it "
                f"reads the SSE stream and returns the aggregated terminal "
                f"result."
            )

        return await c.send_plugin_command(plugin_id, action, params)

    @mcp.tool()
    async def await_streaming_plugin_action(
        plugin_id: str,
        action: str,
        params: dict | None = None,
        timeout_secs: float = DEFAULT_AWAIT_TIMEOUT_SECS,
    ) -> dict:
        """Invoke a streaming plugin action and await the terminal stage.

        Counterpart to ``invoke_plugin_action`` for actions whose
        manifest declares ``stream: true``. POSTs the command, then
        consumes the Server-Sent Events stream at
        ``/plugins/:id/command/:request_id/stream``, aggregating
        progress / item / warning events along the way and stopping
        on a terminal stage (``complete | error | canceled | timeout``).

        Returns a summary:

        ``{
            "stage": "<terminal stage>",
            "request_id": "<uuid>",
            "data": <complete payload, when stage == complete>,
            "error": "<message>" (when stage == error),
            "items": [<aggregated item payloads>],
            "warnings": [<aggregated warning payloads>],
            "progress_history": [<all progress events>],
            "elapsed_secs": <float>,
            "event_count": <int>,
        }``

        Bounded by ``timeout_secs`` (default 90, max 600). The bound
        applies to the *total* await window — if the action declares
        a shorter timeout in its manifest the action's bound wins,
        the SSE stream just delivers the ``timeout`` stage event and
        this tool returns it.

        Write-gated via ``HC_MCP_ALLOW_WRITE=plugin_actions`` (or
        ``all``). Cannot drive ``awaiting_user`` interactive prompts —
        if the action emits one, this tool surfaces it via a
        ``warnings`` entry but cannot respond to it.
        """
        ensure_write(WRITE_CATEGORY)
        if timeout_secs <= 0:
            raise RuntimeError("timeout_secs must be > 0")
        timeout_secs = min(float(timeout_secs), MAX_AWAIT_TIMEOUT_SECS)

        c = client()

        # Resolve action against the manifest so we can hard-fail on
        # non-streaming actions and surface a clear error rather than
        # an SSE-shaped surprise.
        try:
            caps = await c.get_plugin_capabilities(plugin_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' has not published a capability manifest"
                ) from e
            raise
        match = next(
            (a for a in caps.get("actions", []) if a.get("id") == action),
            None,
        )
        if match is None:
            raise RuntimeError(
                f"Action '{action}' not declared by plugin '{plugin_id}'. "
                f"Use list_plugin_actions to see available actions."
            )
        if not match.get("stream"):
            raise RuntimeError(
                f"Action '{action}' on plugin '{plugin_id}' is non-streaming. "
                f"Use `invoke_plugin_action` instead."
            )

        started_at = time.monotonic()
        ack = await c.send_plugin_command(plugin_id, action, params)
        request_id = ack.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            # Non-streaming response shape — shouldn't happen given the
            # manifest check above, but defensive.
            return {
                "stage": "error",
                "request_id": None,
                "error": "plugin returned no request_id; not a streaming action?",
                "ack": ack,
                "elapsed_secs": time.monotonic() - started_at,
                "event_count": 0,
                "items": [],
                "warnings": [],
                "progress_history": [],
            }

        items: list[dict] = []
        warnings: list[dict] = []
        progress: list[dict] = []
        terminal: dict | None = None
        event_count = 0

        async def _consume() -> None:
            nonlocal terminal, event_count
            async for ev in c.stream_plugin_command(
                plugin_id,
                request_id,
                timeout_secs=timeout_secs,
            ):
                event_count += 1
                stage = ev.get("stage", "")
                if stage == "item":
                    items.append(ev.get("data") or ev)
                elif stage == "warning":
                    warnings.append(ev)
                elif stage == "progress":
                    progress.append(ev)
                elif stage == "awaiting_user":
                    # MCP can't drive an interactive prompt round-trip
                    # here — surface it so callers can see the gate
                    # and rerun the action with the responding params
                    # if needed.
                    warnings.append(
                        {
                            "stage": "awaiting_user",
                            "message": "action paused for user input; "
                            "MCP cannot respond, action may time out",
                            "data": ev.get("data"),
                        }
                    )
                elif stage in TERMINAL_STAGES:
                    terminal = ev
                    return

        try:
            await asyncio.wait_for(_consume(), timeout=timeout_secs)
        except TimeoutError:
            terminal = {
                "stage": "timeout",
                "message": (
                    f"await_streaming_plugin_action timed out after "
                    f"{timeout_secs:.1f}s without a terminal stage"
                ),
            }

        terminal = terminal or {"stage": "unknown", "message": "stream closed without terminal"}

        return {
            "stage": terminal.get("stage", "unknown"),
            "request_id": request_id,
            "data": terminal.get("data"),
            "error": terminal.get("error") or terminal.get("message")
            if terminal.get("stage") in {"error", "timeout", "canceled"}
            else None,
            "items": items,
            "warnings": warnings,
            "progress_history": progress,
            "elapsed_secs": round(time.monotonic() - started_at, 3),
            "event_count": event_count,
        }
