"""Plugin-capability action tools (Phase 4).

Two tools:

- ``list_plugin_actions``: discovery — flattens every plugin's capability
  manifest into one list. Always available (read-only).
- ``invoke_plugin_action``: dispatcher — POSTs a non-streaming action
  command. Write-gated behind ``HC_MCP_ALLOW_WRITE=plugin_actions``
  (also satisfied by ``HC_MCP_ALLOW_WRITE=all``).

Streaming actions are intentionally rejected with an explanatory error
in this round. Adding stream-aware invocation (await the terminal stage
via the StreamCache + SSE bridge) is the natural Phase 4b follow-up.
"""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

from ..permissions import ensure_write
from ..server_state import client


WRITE_CATEGORY = "plugin_actions"


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
                f"action. invoke_plugin_action only supports non-streaming "
                f"actions in Phase 4a — Phase 4b will add stream awaiting."
            )

        return await c.send_plugin_command(plugin_id, action, params)
