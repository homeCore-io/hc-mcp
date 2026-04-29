"""Diagnostic / troubleshooting tools.

These wrap the WebSocket /api/v1/logs/stream so the MCP can return a
finite snapshot of recent log lines without keeping a streaming
connection open. Each call connects, accumulates up to ``lines``
matching records, and closes — bounded by ``timeout_secs`` so a quiet
log can't hang the tool.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def core_logs(
        lines: int = 100,
        level: str | None = None,
        grep: str | None = None,
        timeout_secs: float = 5.0,
    ) -> list[dict]:
        """Tail homeCore's structured logs via the live stream.

        Filters:
          - level:        one of trace/debug/info/warn/error (case-insensitive)
          - grep:         regex applied against the message field
          - timeout_secs: how long to wait if `lines` matching records don't arrive

        Returns the next N matching log records (NOT historical — the
        stream is live, so this captures what's emitted starting now,
        plus any in-flight buffered lines hc-core replays on connect).

        Use after triggering an action to see what just happened. For
        post-hoc historical search across all modules, use
        `find_recent_errors`.
        """
        return await client().stream_logs(
            max_lines=lines,
            timeout_secs=timeout_secs,
            level=level,
            grep=grep,
        )

    @mcp.tool()
    async def plugin_logs(
        plugin_id: str,
        lines: int = 100,
        level: str | None = None,
        grep: str | None = None,
        timeout_secs: float = 5.0,
    ) -> list[dict]:
        """Tail a specific plugin's logs.

        Plugins forward their own `tracing` output to the broker on
        homecore/plugins/<id>/logs (see hc-logging::MqttLogLayer);
        hc-core's /logs/stream merges those with its own log stream.
        This tool filters that merged stream by `module = plugin_id`.

        Same filters + timeout semantics as `core_logs`. Useful when a
        plugin is misbehaving and you want only its lines, not the rest
        of homeCore's chatter."""
        return await client().stream_logs(
            max_lines=lines,
            timeout_secs=timeout_secs,
            level=level,
            module=plugin_id,
            grep=grep,
        )

    @mcp.tool()
    async def find_recent_errors(
        lines: int = 50,
        timeout_secs: float = 5.0,
    ) -> list[dict]:
        """Capture the next N WARN-or-higher log records across core +
        every plugin. Use as a first step when "something is broken
        but I don't know where" — fastest way to surface what
        component is unhappy without naming it ahead of time.

        For ERROR-only, use `core_logs` / `plugin_logs` with
        `level = "error"`."""
        records = await client().stream_logs(
            max_lines=lines * 4,  # over-fetch; we'll filter
            timeout_secs=timeout_secs,
        )
        out: list[dict] = []
        for rec in records:
            lv = (rec.get("level") or "").lower()
            if lv in ("warn", "warning", "error"):
                out.append(rec)
                if len(out) >= lines:
                    break
        return out
