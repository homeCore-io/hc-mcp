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
| `await_streaming_plugin_action` | `plugin_actions` | POST + read SSE stream for streaming manifest actions; returns aggregated terminal payload |
| `command_device` | `device_commands` | PATCH `/devices/:id/state` — turn things on/off, set brightness, lock doors, etc. |
| `bulk_command` | `device_commands` | Fan out commands across many devices in parallel; per-device success reported |
| `enable_rule` / `disable_rule` | `rule_mutations` | PATCH `/automations/:id` to flip the enabled flag |
| `delete_rule` | `rule_mutations` | DELETE `/automations/:id` (also patches references in other rules) |
| `create_rule` | `rule_mutations` | POST `/automations` with a full Rule body |
| `update_rule` | `rule_mutations` | PUT `/automations/:id` — full replace of the rule body |

Set `HC_MCP_ALLOW_WRITE` to a comma-separated list of categories (or
`all`) in the hc-mcp environment to enable. Each category is opt-in
independently — for example, `HC_MCP_ALLOW_WRITE=device_commands` lets
Claude turn on lights but not edit rules.

```bash
# In your Claude Desktop / Claude Code MCP server entry:
"env": {
  "HC_MCP_ALLOW_WRITE": "device_commands,rule_mutations,plugin_actions"
}
```

Streaming plugin actions are handled by `await_streaming_plugin_action`,
which reads the SSE stream until a terminal stage and returns the
aggregated result. Tools work universally regardless of how homeCore
was installed (local, docker, remote) — they all go through the REST
API.

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

## Current limitations

- **stdio only.** HTTP/SSE transport (so Claude Desktop on another
  machine can connect over Tailscale) lands in a follow-up.
- **No install-aware substrate.** Tools that would need direct host
  access (journalctl, `docker logs`, config-file reads, service
  restarts) are not yet implemented. The substrate-aware design is
  parked at `claude-notes/plans/hc_mcp_install_aware.md` (DEFERRED).
- **No live MQTT tap.** `mqtt_tap` needs a persistent MQTT client;
  deferred to Phase 4.

## Roadmap

See `DESIGN.md`. Briefly:

- **Phase 3** — plugin scaffolding (`scaffold_plugin`, `check_plugin`).
- **Phase 4 (advanced)** — MQTT tap, rule graph, anomaly detection,
  audit tools.
- **Install-aware substrate** — DEFERRED; revisit after scope review.

## License

Apache-2.0 OR MIT.
