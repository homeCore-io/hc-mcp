# hc-mcp

Model Context Protocol server for [homeCore](https://github.com/homeCore-io/homeCore).
Exposes typed tools that an MCP-aware LLM client (Claude Desktop, Claude
Code, etc.) can call to inspect a running homeCore instance.

**Status:** read and write tools for MCP clients, and (0.1.1) the same tools
as the homeCore app's Assistant chat; see "The Assistant" below. Roadmap and
full tool inventory live in [`DESIGN.md`](DESIGN.md).

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
| `device_state` | `GET /devices/:id` + `/schema` | Single device + schema |
| `device_history` | `GET /devices/:id/history` | Time-series for a device attribute |
| `list_rules` | `GET /automations` | All automations |
| `get_rule` | `GET /automations/:id` | One automation full body |
| `rule_firings` | `GET /automations/:id/history` | Recent fire history |
| `rule_test` | `POST /automations/:id/test` | Dry-run a rule against current state, or as of a time (`at`) |
| `test_draft_rule` | `POST /automations/test` | Dry-run a rule body before saving it |
| `recent_events` | `GET /events` | Tail of the event ring buffer |
| `correlation_trace` | client-side filter | Walk a command's life cycle by the `correlation_id` `command_device` returns |
| `core_logs` | `GET /logs` | The newest lines of homeCore's log (`level`, `target`, `since`, `grep`) |
| `plugin_logs` | `GET /logs?plugin_id=` | The same for one plugin's process |
| `find_recent_errors` | `GET /logs?level=warn` | Warnings and errors across core + every plugin |
| `list_plugin_actions` | (caps fanout) | Flatten every plugin manifest into one list of actions |
| `query_plugin_action` | `POST /plugins/:id/query` | Run a plugin action that only reads |
| `plugin_health` | `GET /plugins` | Every plugin's health and notices, the ones needing attention first |
| `list_alerts` | `GET /alerts` | What needs attention now (wet, smoke, jammed, battery, offline, rules, plugins) |
| `audit_log` | `GET /audit` | Who changed what, filtered by event, actor, target, result and time |
| `paused_rules` | `GET /automations/paused` | Automations another automation has paused |
| `stale_rule_refs` | `GET /automations/stale-refs` | Automations naming devices that no longer exist |
| `hub_variables` | `GET /automations/variables` | The variables automations have set, as they are now |
| `orphaned_devices` | `GET /devices/orphaned` | Devices no plugin manages any more |
| `vocabulary_check` | `GET /system/vocabulary-check` | Commands and conditions a device won't take, and why |
| `system_versions` | `GET /system/versions` | Which version of everything is running |
| `plugin_runtimes` | `GET /plugin-runtimes` + `/placements` | Runtimes, their health, and which plugins run where (admin) |
| `list_backups` | `GET /system/backups` | The scheduled backups homeCore keeps (admin) |
| `list_scenes` / `list_rooms` | `GET /scenes`, `GET /areas` | The house's scenes and rooms, by id and name |

The three log tools need an admin's key: homeCore serves logs to admins
only, and an API key is an admin only if it holds `users:write`. The key
`hc-mcp setup` makes leaves that out on purpose (`users:write` can make
users and keys); add it with `--scopes` if hc-mcp should read logs.

### Write-gated (require `HC_MCP_ALLOW_WRITE`)

| Tool | Category | Effect |
|---|---|---|
| `invoke_plugin_action` | `plugin_actions` | POST `/plugins/:id/command` for non-streaming manifest actions (`/query` for read-only ones) |
| `await_streaming_plugin_action` | `plugin_actions` | POST + read SSE stream for streaming manifest actions; returns aggregated terminal payload |
| `command_device` | `device_commands` | PATCH `/devices/:id/state` — turn things on/off, set brightness, lock doors, etc. |
| `bulk_command` | `device_commands` | Fan out commands across many devices, 8 at a time; per-device success reported |
| `run_scene` | `device_commands` | POST `/scenes/:id/activate` |
| `acknowledge_alert` | `device_commands` | POST `/alerts/:id/acknowledge` — marks it seen; it stays until it clears |
| `room_lights` | `device_commands` | POST `/areas/:id/on|off` — a room's lights only, restored as they were |
| `resume_rule` | `rule_mutations` | DELETE `/automations/:id/pause` — undo another automation's pause |
| `plugin_control` | `plugin_actions` | POST `/plugins/:id/start|stop|restart` (plugins homeCore runs) |
| `set_plugin_log_level` | `plugin_actions` | PATCH `/plugins/:id` `log_level` — lasts; put it back after debugging |
| `enable_rule` / `disable_rule` | `rule_mutations` | PATCH `/automations/:id` to flip the enabled flag |
| `delete_rule` | `rule_mutations` | DELETE `/automations/:id` — permanent; read it first if it might be wanted again |
| `create_rule` | `rule_mutations` | POST `/automations` with a full Rule body |
| `update_rule` | `rule_mutations` | PUT `/automations/:id` — full replace of the rule body |

Set `HC_MCP_ALLOW_WRITE` to a comma-separated list of categories (or
`all`) in the hc-mcp environment to enable. Each category is opt-in
independently — for example, `HC_MCP_ALLOW_WRITE=device_commands` lets
Claude turn on lights but not edit rules.

**Locks, doors and security.** A change that touches a device counting
for security (locks, doors, windows, covers, garages, alarms, or any
device marked so) also needs `security` in the list:
`HC_MCP_ALLOW_WRITE=device_commands,security`. That covers a device
command, a scene or automation that names one, and a plugin action that
names one or belongs to a plugin that owns one (a read-only action never
counts). `all` includes it. The in-app chat applies the same check, with
its "Locks, doors and security" setting.

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

## Skills: how-to guides

hc-mcp ships homeCore's skills from
[homeCore-io/skills](https://github.com/homeCore-io/skills):
`dev-environment`, `install-and-setup` and `plugin-development`. An MCP client
sees each as a prompt (start a conversation with it), can read every file as a
`homecore-skill://<skill>/<file>` resource, and has two tools, `list_skills`
and `read_skill`. The Assistant knows the skills by name and reads one when
someone asks how to do something.

The copy lives in `hc_mcp/skills`. After the skills repo changes, refresh it
with `scripts/sync-skills.sh` (it reads `../../skills`, or a path you give it).

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
hc-mcp setup --base-url http://192.168.1.10:8080 \
             --admin-token "$ADMIN_JWT"

# Option B — log in via /auth/login first:
hc-mcp setup --base-url http://192.168.1.10:8080 \
             --username admin
# (password prompted on stdin)

# To rotate the key on a host that's already configured:
hc-mcp setup --rotate
```

Defaults: label `hc-mcp`, scopes
`areas:read,automations:read,automations:write,audit:read,devices:command,devices:read,plugins:read,plugins:write,scenes:read,scenes:run`
(the scope behind each `HC_MCP_ALLOW_WRITE` category, so allowing one works),
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

Add to `~/.claude.json` (or a project's `.mcp.json`):

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

## The Assistant: hc-mcp inside the homeCore app

The same tools also run as a homeCore plugin, `plugin.mcp` ("Assistant"):
an **Ask** button on every page of the app opens a chat with Claude about the
house. Everyone signed in can chat; it never goes beyond what the person
asking may do.

```bash
hc-mcp plugin /path/to/config.toml        # by hand
python -m hc_mcp.plugin /path/to/config.toml   # how a Python runtime runs it
```

homeCore passes the config file (its `[homecore]` table: broker and plugin
credentials), mints the plugin its own REST key on every start (the manifest's
`api_scopes`; nothing to paste), and says who is asking with every action.
The plugin needs `homecore-plugin-sdk` 0.5.6 or later.

**Settings** (Settings > Plugins > Assistant, admins only): the Claude API key
(from console.anthropic.com; stored by the plugin, never sent back to a
browser), the model (Claude Sonnet 5.5 by default, Opus 5.5, Haiku 4.5), what
it may do (control devices, make and change automations, locks, doors and
security, ask before every change) and how long chats are kept (30 days, 7
days, or not at all).

**What it may do in chat** is the intersection of three things: the tool's
category is switched on in the settings, the person asking holds the tool's
homeCore scopes, and the plugin's own key does. Anything that changes the
house shows a confirm card first (unless "Ask before every change" is off),
and a device that counts for security needs "Locks, doors and security" too.

**Where it keeps things**: `settings.json` and one folder of chats per
person, in its data folder: `HC_MCP_DATA_DIR`, else `[assistant].data_dir`
in the config, else (in a runtime) `.../plugins/plugin.mcp/data` so upgrades
keep it, else `hc-mcp-data` beside the config. Chats never go to homeCore.

**The screens** ship in `ui/` (plain custom elements, no build step):
`hc-mcp-chat` (slot `app.assistant`) and `hc-mcp-settings` (slot
`plugin.page`). The wheel carries them as `hc_mcp/ui`. What the chat action
streams to them is in [`docs/chat-events.md`](docs/chat-events.md).

### Releasing the plugin

Bump the version in `pyproject.toml` and `hc_mcp/__init__.py`, merge to
`main` and tag `v<version>`. `.github/workflows/release.yml` calls hc-scripts'
`python-release.yml`, which builds the runtime artifact (the plugin, the SDK
and every dependency as wheels, for x86_64 and aarch64), installs it offline
and starts it against a broker, then publishes the release and lists it in the
registry, where the Catalog finds it.

To build the artifact by hand: `hc-scripts/build-python-artifact.sh --plugin
clients/hc-mcp --sdk sdks/hc-plugin-sdk-py`.

## Current limitations

- **stdio only.** HTTP/SSE transport (so Claude Desktop on another
  machine can connect over Tailscale) lands in a follow-up.
- **No install-aware substrate.** Tools that would need direct host
  access (journalctl, `docker logs`, config-file reads, service
  restarts) are not yet implemented.
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
