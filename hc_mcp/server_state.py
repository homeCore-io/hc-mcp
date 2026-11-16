"""Which ``HomeCoreClient`` the tools talk through.

Tools call ``client()`` to get it, which keeps every tool body a one-liner
without passing the client through each function.

Two ways it is set:

- ``set_client()``, once, from ``server.main()``: the MCP server has one
  client for its whole life.
- ``using_client()``, around one chat turn in plugin mode: each turn runs on
  its own event loop with its own client (the plugin's REST key can be
  reminted between turns), so it is a context variable rather than a global.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .homecore_client import HomeCoreClient

_client: HomeCoreClient | None = None
_current: ContextVar[HomeCoreClient | None] = ContextVar("hc_mcp_client", default=None)


def set_client(c: HomeCoreClient) -> None:
    global _client
    _client = c


@contextmanager
def using_client(c: HomeCoreClient) -> Iterator[HomeCoreClient]:
    """Run the tools inside this block against *c*."""
    token = _current.set(c)
    try:
        yield c
    finally:
        _current.reset(token)


def client() -> HomeCoreClient:
    c = _current.get() or _client
    if c is None:
        raise RuntimeError("hc-mcp: HomeCoreClient not initialised; call set_client() first")
    return c
