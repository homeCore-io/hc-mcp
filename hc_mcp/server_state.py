"""Module-level holder for the shared ``HomeCoreClient`` instance.

Tools call ``client()`` to get the singleton. ``set_client()`` is called
once from ``server.main()`` after config has been loaded — keeps the
tool function bodies one-liners without passing the client through every
registration callable.
"""

from __future__ import annotations

from .homecore_client import HomeCoreClient

_client: HomeCoreClient | None = None


def set_client(c: HomeCoreClient) -> None:
    global _client
    _client = c


def client() -> HomeCoreClient:
    if _client is None:
        raise RuntimeError("hc-mcp: HomeCoreClient not initialised; call set_client() first")
    return _client
