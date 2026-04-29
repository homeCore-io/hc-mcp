# hc-mcp

Model Context Protocol server for [homeCore](https://github.com/homeCore-io/homeCore).
Exposes typed tools that an MCP-aware LLM client (Claude Desktop, Claude
Code, etc.) can call to inspect a running homeCore instance.

**Status:** Phase 1 — read-only troubleshooter. Roadmap and full tool
inventory live in [`DESIGN.md`](DESIGN.md).

## Tools

### Read-only (always on)

| Tool | Endpoint | Use |
|---|---|---|
| `system_health` | `GET /system/status` | First-stop overall health |
| `broker_diagnose` | aggregated | MQTT broker + plugin heartbeat sanity check |
| `list_plugins` | `GET /plugins` | Status of every plugin |
| `plugin_status` | `GET /plugins/:id` | One plugin in detail |
| `plugin_capabilities` | `GET /plugins/:id/capabilities` | Declared actions for a plugin |
| `list_devices` | `GET /devices` | Registered devices + state |
| `device_state` | `GET /devices/:id` | Single device + schema |
| `device_history` | `GET /devices/:id/history` | Time-series for a device attribute |
| `list_rules` | `GET /automations` | All automations |
| `get_rule` | `GET /automations/:id` | One automation full body |
| `rule_firings` | `GET /automations/:id/history` | Recent fire history |
| `rule_test` | `POST /automations/:id/test` | Dry-run a rule against current state |
| `recent_events` | `GET /events` | Tail of the event ring buffer |
| `correlation_trace` | client-side filter | Walk a single command's life cycle by correlation_id |
| `core_logs` | `WS /logs/stream` | Tail of homeCore's structured logs |
| `plugin_logs` | `WS /logs/stream` | Same, filtered to one plugin |
| `find_recent_errors` | `WS /logs/stream` | WARN/ERROR across core + every plugin |
| `list_plugin_actions` | (caps fanout) | Flatten every plugin manifest into one list of actions |

### Write-gated (require `HC_MCP_ALLOW_WRITE`)

| Tool | Category | Effect |
|---|---|---|
| `invoke_plugin_action` | `plugin_actions` | POST `/plugins/:id/command` for non-streaming manifest actions |

Set `HC_MCP_ALLOW_WRITE=plugin_actions` (or `all`) in the hc-mcp environment to enable. Streaming actions return an explanatory error in this round — Phase 4b will add a stream-aware variant that awaits the terminal stage.

## Install

```bash
cd clients/hc-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

Python ≥ 3.11 required (TOML stdlib + modern type syntax).

## Configure

The packaged `hc-mcp setup` command issues an API key against a running
homeCore and writes the config file at `~/.config/hc-mcp/config.toml`
(0600). Two auth paths into homeCore:

```bash
# Option A — already have an admin JWT (e.g. from the admin UI's
#            "API tokens" panel):
hc-mcp setup --base-url http://10.0.10.20:8080 \
             --admin-token "$ADMIN_JWT"

# Option B — log in via /auth/login first:
hc-mcp setup --base-url http://10.0.10.20:8080 \
             --username admin
# (password prompted on stdin)

# To rotate the key on a host that's already configured:
hc-mcp setup --rotate
```

Defaults: label `hc-mcp`, scopes
`areas:read,automations:read,audit:read,devices:read,plugins:read,plugins:write,scenes:read`,
no expiry. Override with `--label`, `--scopes a,b,c`, `--expires-days N`.

> The admin JWT is only used for the `/auth/api-keys` POST during
> setup — hc-mcp never stores it. The persisted config holds only the
> generated long-lived API key.

### Manual fallback

If you'd rather not run setup, write the config yourself:

```toml
[homecore]
base_url = "http://127.0.0.1:8080"
api_key  = "hc_sk_…"        # from the admin UI or a prior setup run
# timeout_secs = 30.0
```

…or set `HC_MCP_BASE_URL` / `HC_MCP_API_KEY` env vars.

## Wire into a Claude client

### Claude Code

Add to `~/.claude.json` (or per-project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "homecore": {
      "command": "/path/to/hc-mcp/.venv/bin/hc-mcp"
    }
  }
}
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or the equivalent on your platform — same shape as above.

## Run standalone

To smoke-test outside an MCP client:

```bash
.venv/bin/hc-mcp --help
```

The server speaks MCP over stdio; you can drive it with the MCP
inspector or any conformant client.

## Phase 1 limitations

- **stdio only.** HTTP/SSE transport (so Claude Desktop on another
  machine can connect over Tailscale) lands in a follow-up.
- **Read-only.** No `command_device`, `create_rule`, or `scaffold_plugin`
  yet — those are gated behind a future `HC_MCP_ALLOW_WRITE` flag.
- **No live MQTT tap.** `mqtt_tap` and `correlation_trace` need a
  persistent MQTT client; deferred to Phase 4.

## Roadmap

See `DESIGN.md`. Briefly:

- **Phase 2** — device + rule write tools + write-category gating.
- **Phase 3** — plugin scaffolding (`scaffold_plugin`, `check_plugin`).
- **Phase 4** — MQTT tap, rule graph, anomaly detection, audit tools.

## License

Apache-2.0 OR MIT.
