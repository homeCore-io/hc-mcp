"""hc-mcp server entrypoint.

Phase 1: stdio transport, read-only tools, API-key auth.

Run with:

    hc-mcp                       # uses ~/.config/hc-mcp/config.toml
    hc-mcp --config path.toml    # explicit config
    HC_MCP_API_KEY=hc_sk_... hc-mcp   # env-var override

Register with Claude Desktop / Claude Code by adding an MCP server entry
that runs `hc-mcp` (see README.md).
"""

from __future__ import annotations

import argparse
import sys

from mcp.server.fastmcp import FastMCP

from . import config as cfg_mod
from . import server_state
from .homecore_client import HomeCoreClient
from .tools import (
    devices,
    events,
    plugin_actions,
    plugins,
    rules,
    system,
    troubleshooting,
)


def build_server(client: HomeCoreClient) -> FastMCP:
    mcp = FastMCP("hc-mcp")
    server_state.set_client(client)
    system.register(mcp)
    plugins.register(mcp)
    devices.register(mcp)
    rules.register(mcp)
    events.register(mcp)
    plugin_actions.register(mcp)
    troubleshooting.register(mcp)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="hc-mcp", description=__doc__)
    parser.add_argument("--config", help="Path to TOML config", default=None)
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
        help="MCP transport. Phase 1 ships stdio only; HTTP/SSE comes later.",
    )
    args = parser.parse_args()

    try:
        config = cfg_mod.load(args.config)
    except RuntimeError as e:
        # Surface auth setup issues clearly — Claude Code shows MCP stderr.
        print(f"hc-mcp: {e}", file=sys.stderr)
        sys.exit(2)

    client = HomeCoreClient(config)
    server = build_server(client)

    if args.transport == "stdio":
        server.run("stdio")
    else:  # pragma: no cover — argparse choices keeps us out of here
        raise SystemExit(f"unknown transport: {args.transport}")
