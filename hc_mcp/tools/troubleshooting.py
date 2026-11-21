"""Diagnostic / troubleshooting tools.

All three read ``GET /api/v1/logs``: the newest matching lines of the ring
buffer homeCore keeps of its own log and every plugin's, filtered on the
server. That is real history, so a tool call can look back at what already
happened; to see what an action just caused, note the time first and pass
it as ``since``.

homeCore serves logs to admins only. A user's token counts if they are an
admin; an API key counts only if it holds ``users:write``.
"""

from __future__ import annotations

import re

import httpx

from ..server_state import client

#: GET /logs returns at most this many lines.
MAX_LINES = 1000

_NEEDS_ADMIN = (
    "homeCore serves logs to admins only, and this key isn't one. An API key "
    "counts as an admin only if it holds the users:write scope: use an admin "
    "user's key, or make a key with users:write for hc-mcp."
)


async def _read(
    *,
    lines: int,
    level: str | None,
    plugin_id: str | None = None,
    target: str | None = None,
    since: str | None = None,
    grep: str | None = None,
) -> dict:
    lines = max(1, min(lines, MAX_LINES))
    grep_re = re.compile(grep) if grep else None
    try:
        got = await client().logs(
            level=level,
            plugin_id=plugin_id,
            target=target,
            since=since,
            # A grep filters what came back, so ask for the most there is.
            limit=MAX_LINES if grep_re else lines,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise PermissionError(_NEEDS_ADMIN) from e
        if e.response.status_code == 503:
            raise RuntimeError("Log streaming is turned off in homeCore's config.") from e
        raise
    out = got.get("lines", []) if isinstance(got, dict) else []
    if grep_re:
        out = [ln for ln in out if grep_re.search(ln.get("message", ""))][-lines:]
    return {"count": len(out), "lines": out}


async def core_logs(
    lines: int = 100,
    level: str = "info",
    target: str | None = None,
    since: str | None = None,
    grep: str | None = None,
) -> dict:
    """The newest lines of homeCore's log, oldest first: core's own lines
    and every plugin's.

    Filters, all optional:
      - level:  the least severe level to include: trace, debug, info
                (default), warn or error
      - target: a module prefix, such as ``hc_core::engine``
      - since:  an RFC 3339 time; only lines after it. Note the time before
                you trigger something, then read what followed.
      - grep:   a regular expression matched against each line's message

    Returns ``{count, lines}``; each line has timestamp, level, target,
    message and fields (a plugin's lines carry ``fields.plugin_id``). At
    most 1000 lines. Logs are for admins: a key without users:write is
    refused."""
    return await _read(lines=lines, level=level, target=target, since=since, grep=grep)


async def plugin_logs(
    plugin_id: str,
    lines: int = 100,
    level: str = "info",
    since: str | None = None,
    grep: str | None = None,
) -> dict:
    """The newest lines one plugin's process logged, oldest first.

    ``plugin_id`` is exact (``plugin.hue``), and catches everything that
    process emitted: its own modules, the SDK's and its dependencies'.
    Same ``level``, ``since`` and ``grep`` filters as ``core_logs``. Use it
    when a plugin is misbehaving and you want only its lines."""
    return await _read(lines=lines, level=level, plugin_id=plugin_id, since=since, grep=grep)


async def find_recent_errors(
    lines: int = 50,
    since: str | None = None,
) -> dict:
    """The newest warnings and errors across core and every plugin, oldest
    first. A first step when something is wrong and you don't yet know
    where: each line's ``target`` and ``fields.plugin_id`` say which part
    is unhappy.

    For errors alone, use ``core_logs`` with ``level = "error"``."""
    return await _read(lines=lines, level="warn", since=since)
