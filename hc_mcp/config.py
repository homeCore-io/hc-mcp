"""Configuration loader for hc-mcp.

Resolution order (first hit wins):

1. Path passed via ``--config``.
2. ``HC_MCP_CONFIG`` env var.
3. ``~/.config/hc-mcp/config.toml``.

Individual fields can also be overridden by env vars
(``HC_MCP_BASE_URL``, ``HC_MCP_API_KEY``, ``HC_MCP_TIMEOUT_SECS``) so the
server can run unconfigured for ad-hoc invocations from Claude Code's
settings.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    timeout_secs: float

    @staticmethod
    def default_path() -> Path:
        return Path.home() / ".config" / "hc-mcp" / "config.toml"


def load(explicit_path: str | None = None) -> Config:
    """Load config from a TOML file, with env-var overrides on top."""
    path = _resolve_path(explicit_path)
    file_data: dict = {}
    if path is not None and path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        file_data = raw.get("homecore", {})

    base_url = (
        os.environ.get("HC_MCP_BASE_URL")
        or file_data.get("base_url")
        or "http://127.0.0.1:8080"
    )
    api_key = os.environ.get("HC_MCP_API_KEY") or file_data.get("api_key")
    if not api_key:
        raise RuntimeError(
            "hc-mcp: missing API key. Set HC_MCP_API_KEY or write "
            "[homecore].api_key in ~/.config/hc-mcp/config.toml. Issue a key "
            "with `hc-cli api-key issue --owner mcp-service --role observer`."
        )
    timeout_raw = os.environ.get("HC_MCP_TIMEOUT_SECS") or file_data.get("timeout_secs", 5)
    timeout_secs = float(timeout_raw)

    return Config(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout_secs=timeout_secs,
    )


def _resolve_path(explicit_path: str | None) -> Path | None:
    if explicit_path:
        return Path(explicit_path)
    env_path = os.environ.get("HC_MCP_CONFIG")
    if env_path:
        return Path(env_path)
    default = Config.default_path()
    return default if default.exists() else None
