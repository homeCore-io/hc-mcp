# hc-mcp — Design Plan

> Model Context Protocol server for homeCore. Written in Python using the
> official Anthropic `mcp` SDK. Exposes typed tools Claude can call for
> troubleshooting, rule creation, plugin scaffolding, and more.

**Status:** Phase 1 (read-only troubleshooter) + Phase 2 (device + rule
mutation) + Phase 4a/4b (plugin action dispatcher + streaming-action
awaiter) shipped. Phase 3 (plugin scaffolding) pending. An
install-aware substrate proposal (Tier B / InstallContext) is parked at
`claude-notes/plans/hc_mcp_install_aware.md` (DEFERRED — needs scope
review before resuming).

---

## The Assistant (0.2.0): the same tools as a chat in the app

hc-mcp also runs as a homeCore plugin, `plugin.mcp`, behind an "Ask" button in
the app. The pieces:

- **One registry** (`hc_mcp/registry.py`). Every tool is a plain async
  function in `hc_mcp/tools/`, listed once with its category (`read`,
  `device_commands`, `rule_mutations`, `plugin_actions`; `security` gates
  devices rather than tools), the homeCore scopes it needs, and the chip the
  chat shows once it ran. The MCP server registers from it under the same names
  and schemas as before, gated by `HC_MCP_ALLOW_WRITE` as before. A few tools
  are chat only (`list_scenes`, `run_scene`, `list_rooms`, and the screen tools
  `show_devices` and `suggest_replies`); the log tools are MCP only, since
  homeCore serves logs to admins and the plugin's key is never one.
- **The chat loop** (`hc_mcp/chat.py`) asks the model, runs the tools it calls,
  and asks again, at most 12 rounds. The model sees only the tools whose
  category is on in the settings and whose scopes the person asking holds (and
  the plugin's key holds). Changes go through a confirm card when "Ask before
  every change" is on; a device that counts for security (its `security`
  choice, else its type: locks, doors, windows, covers) needs "Locks, doors and
  security" as well, checked for device commands, scenes and automations.
- **A small provider interface** (`hc_mcp/provider.py`): reply (streaming text,
  returning content, tool calls and why it stopped), the two message shapes,
  and a key check. Only the Claude API is built (`anthropic` 2.x, Messages API
  with tool use, streamed). An OpenAI-compatible or local endpoint would be one
  more class.
- **The plugin** (`hc_mcp/plugin.py`): declares `api_scopes`, the streaming
  `chat` action (`requires_role: signed_in`, many at once, cancelable) and the
  immediate ones the screens use; keeps settings and each person's chats in its
  own data folder. A missing key, an API failure, or REST access that has not
  arrived never stops it: it logs, raises a notice, and the chat says so.
- **The screens** (`ui/`): `hc-mcp-chat` (slot `app.assistant`) and
  `hc-mcp-settings` (slot `plugin.page`), built to the approved mockups in the
  app's own colors. The stream between them is documented in
  [`docs/chat-events.md`](docs/chat-events.md).

What the chat cannot know: the words on an automation's confirm card are the
model's own description (`explain`), shown beside the exact rule; homeCore's
rule JSON has no plain-language renderer the plugin could use instead.

---

## What MCP means here

An MCP server exposes typed tools to Claude (or any LLM client). Each tool is
a Python function with a description + JSON schema. Claude chooses when to
call them based on conversation. So the design question is: **what should
Claude be empowered to do with your home?** Split read (safe) vs write
(blast-radius considered) tools deliberately.

Python is the right fit — official `mcp` Python SDK is mature, and the
existing `hc-plugin-sdk-py` gives MQTT primitives for free.

---

## Core capabilities (user-requested)

### 1. Troubleshooting ("why isn't X working?")

Highest-value category — LLMs excel at correlating symptoms across
log/state/config sources.

**Read tools:**
- `system_health` — core uptime, broker, DB sizes, plugin roster with status/heartbeat ages
- `plugin_status(plugin_id)` — status, last heartbeat, config path, last log error, device count
- `plugin_logs(plugin_id, lines=100, level=null, grep=null)` — tail with filters
- `core_logs(lines=100, level=null, grep=null, since=null)` — same for core
- `device_state(device_id)` — current attributes + availability + last_change metadata
- `device_history(device_id, attribute=null, from=null, to=null, limit=500)`
- `rule_firings(rule_id, limit=20)` — recent fire events with per-condition/action outcomes
- `rule_test(rule_id)` — wraps existing dry-run endpoint
- `broker_diagnose()` — broker reachable, subscriptions present, ACL issues
- `correlation_trace(correlation_id)` — walk command → state change → rule firings
- `find_recent_errors(since_minutes=15)` — aggregate ERROR/WARN across core + all plugin logs
- `mqtt_tap(topic_filter, duration_secs)` — subscribe briefly, return captured messages

### 2. Rule creation

**Inspection:**
- `list_rules(tag=null, enabled=null, device=null)`
- `get_rule(id)` — full RON/JSON
- `rule_dependencies(id)` — devices, scenes, modes referenced
- `find_rules_affecting(device_id)` — reverse lookup

**Mutation:**
- `create_rule(rule_spec)` — validates via core's dry-run then POSTs
- `update_rule(id, patch)` — partial update
- `enable_rule(id)` / `disable_rule(id)`
- `test_rule(rule_spec)` — validate-only (no save)
- `suggest_rule_template(intent)` — returns starter specs for common patterns
  ("notify on stale sensor", "turn on at sunset", "cooldown timer")

### 3. Plugin development — scaffold + conformance

**Scaffolding:**
- `scaffold_plugin(name, language, device_types=[], capabilities={})` — creates full plugin directory matching homeCore conventions:
  - Rust: `Cargo.toml` + `main.rs` + `config.rs` + `logging.rs` + `Justfile` + dual `LICENSE-*` + `README.md` + `.gitignore` + `config/config.toml.example` + `tests/config_tests.rs`
  - Python / JS / .NET: analogous, using matching SDK
  - Templates parameterized via Jinja2 (`hc_mcp/templates/<language>/`)
- `add_management_action(plugin_path, action_name, schema)` — inject a `with_custom_handler` arm with boilerplate
- `add_device_type(plugin_path, device_type, capabilities)` — append config parsing + registration

**Conformance check:**
- `check_plugin(plugin_path)` — returns a checklist:
  - ✅/❌ uses `plugin-sdk-{rs,py,js,dotnet}`
  - ✅/❌ connects then spawns `run_managed` before registering (SDK deadlock rule)
  - ✅/❌ publishes heartbeat + `device_count`
  - ✅/❌ activates `MqttLogLayer` after connect
  - ✅/❌ handles management protocol (get/set config, set_log_level, ping)
  - ✅/❌ has `config.toml.example` committed, others gitignored
  - ✅/❌ appears in workspace Justfile plugin list
  - ✅/❌ README follows template structure

- `explain_sdk_pattern(topic)` — "cross-device consumer", "custom management handler", "per-device subscription" — pulls from SDK docs + returns code snippets.

---

## Additional categories (brainstorm, rough priority order)

### 4. Device operations
- `list_devices(filter)` — by area, plugin, type, availability, attribute predicate
- `command_device(id, command)` — optional dry-run + confirmation gate
- `bulk_command(filter, command)` — capped fan-out, requires `confirm=true`
- `resolve_device(natural_language)` — "the kitchen sensor" → device_id (fuzzy match on name + area). Probably a helper, not a user-visible tool.

### 5. Configuration management
- `get_plugin_config(plugin_id)` / `set_plugin_config(plugin_id, toml_string)` — over management RPC
- `validate_config(plugin_id, toml_string)` — schema-check without applying
- `diff_configs(plugin_id, other_path)` — prod↔dev comparisons
- `export_all_config(output_dir)` — full snapshot: homecore.toml, all plugin configs, rules, scenes, modes

### 6. Historical / analytical
- `history_summary(device_id, from, to, aggregation)` — min/max/mean/stddev
- `detect_anomalies(device_id, window)` — sudden silence, outliers, stuck values
- `activity_timeline(from, to, filter)` — event stream as readable narrative
- `explain_period(from, to)` — "what happened between 2am and 3am?" — tool pulls events + rule firings + state changes + log errors; Claude synthesizes

### 7. Scene / mode / automation inspection
- `list_scenes()`, `scene_targets(id)`
- `list_modes()`, `mode_rules(mode_id)` — rules gated by this mode
- `simulate_scene(id)` — dry-run what would change

### 8. Rule analysis (complementary to rule creation)
- `rule_graph(device_id | scene_id | mode_id)` — dependency graph: who references this, what does it reference
- `find_unused(devices|scenes|modes|rules)` — cruft detection
- `find_broken(rules)` — rules in error state (e.g. deleted device refs)

### 9. System observability
- `metrics_snapshot()` — Prometheus-style counters/gauges
- `active_timers()` / `active_delays()` — currently running
- `backup_status()` — last backup, size

### 10. Testing / simulation
- `spawn_virtual_device(schema, initial_state)` — via existing virtual-device plugin
- `inject_state(device_id, state)` — for testing rule triggers
- `run_rule_scenario(rule_id, event_sequence)` — scripted events, report firings
- `simulate_time(date_time)` — only useful if core supports time-override (currently doesn't; would need feature flag)

### 11. Security auditing
- `audit_acls()` — check each plugin's ACL against topics it actually uses (requires brief MQTT tap)
- `find_secrets_in_configs()` — regex scan for leaked credentials
- `check_exposed_endpoints()` — any rules calling arbitrary URLs?

### 12. Migration / refactoring
- `rename_device(old_id, new_id)` — updates rules, scenes, glue refs, modes
- `move_device(id, new_area)`
- `convert_rule(id, format)` — TOML↔RON↔JSON
- `split_plugin(source_plugin_id, device_filter, new_plugin_id)` — ambitious

### 13. Documentation / onboarding
- `docs_search(query)` — Docusaurus site indexed; MCP fetches relevant pages
- `explain_concept(topic)` — canonical doc section
- `suggest_next_step()` — context-aware hints

### 14. Proactive / monitoring (needs daemon mode)
- Would require MCP to push notifications to Claude rather than just respond. Not standard MCP — possible via "what changed since last query?" tool or ScheduleWakeup-style triggers from Claude Code.

### 15. Scripting / evaluation
- `eval_rhai(script, context)` — try a rule's Rhai expression against live state
- `inspect_template_rendering(template, data)` — Jinja/template preview

---

## Design decisions to resolve before coding

### 1. Read vs write split
Group write tools (`command_device`, `create_rule`, `scaffold_plugin`,
`set_plugin_config`) so Claude can run read-only by default. Write
categories should be opt-in via env var or config (`HC_MCP_ALLOW_WRITE=commands,rules,configs`).

### 2. Transport
- **stdio** for local Claude Code use (run `hc-mcp` as subprocess)
- **HTTP/SSE** for remote Claude Desktop on another machine

Support both — trivial with Python SDK.

### 3. Auth
MCP server needs a homeCore admin JWT. Options:
- (a) Generate a dedicated "mcp-service" user at setup. **Prefer this** — audit logs show MCP as the actor.
- (b) MCP accepts JWT from env var.

### 4. Rate limits / blast radius
- Write operations logged with correlation_id prefix "mcp-" for auditability
- `bulk_command` requires `confirm: true` and caps fan-out (~50 devices max)

### 5. Stateful vs stateless
MCP is stateless per-request by default. `mqtt_tap` / `correlation_trace`
want a persistent MQTT client — handle with internal connection pool +
session-scoped subscriptions that clean up on shutdown.

### 6. Scaffolding templates
Jinja2 templates under `hc_mcp/templates/<language>/plugin/*` — versioned
with MCP, updated as SDK patterns evolve.

### 7. Conformance checks vs lint
`check_plugin` can either invoke `cargo check`/`cargo clippy` (heavy,
requires toolchain) or pure static AST analysis. **Start with static** —
faster, no toolchain dependency.

### 8. Natural-language device resolution
`resolve_device("kitchen sensor")` is harder than it looks. Build once as a
helper, reuse across any tool taking a `device_id`. Don't expose as a
top-level tool — let Claude call it implicitly.

---

## Proposed repository layout

```
clients/hc-mcp/
├── pyproject.toml
├── README.md
├── DESIGN.md                  (this file)
├── config.example.toml
├── hc_mcp/
│   ├── __init__.py
│   ├── server.py              # MCP server entry (stdio + HTTP/SSE)
│   ├── auth.py                # JWT acquisition + refresh
│   ├── homecore_client.py     # REST API wrapper
│   ├── mqtt.py                # Persistent MQTT client for tap/trace
│   ├── permissions.py         # Read/write category gating
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── troubleshooting.py
│   │   ├── devices.py
│   │   ├── rules.py
│   │   ├── plugins.py
│   │   ├── scaffolding.py
│   │   ├── scenes_modes.py
│   │   ├── history.py
│   │   ├── audit.py
│   │   └── docs.py
│   ├── templates/
│   │   ├── rust/
│   │   │   └── plugin/
│   │   │       ├── Cargo.toml.j2
│   │   │       ├── src/
│   │   │       │   ├── main.rs.j2
│   │   │       │   ├── config.rs.j2
│   │   │       │   └── logging.rs.j2
│   │   │       ├── Justfile.j2
│   │   │       ├── README.md.j2
│   │   │       └── config/config.toml.example.j2
│   │   ├── python/plugin/...
│   │   ├── javascript/plugin/...
│   │   └── dotnet/plugin/...
│   └── rule_templates.py      # Starter specs for suggest_rule_template
└── tests/
    ├── test_scaffolding.py
    ├── test_rule_templates.py
    └── fixtures/
```

---

## Phased delivery plan

Each phase is shippable independently.

### Phase 1 — Read-only troubleshooter ✅ (shipped 2026-04-29)
Tools live: `system_health`, `broker_diagnose`, `list_plugins`,
`plugin_status`, `plugin_capabilities`, `list_devices`, `device_state`,
`device_history`, `list_rules`, `get_rule`, `rule_firings`, `rule_test`,
`recent_events`, `correlation_trace`, `core_logs`, `plugin_logs`,
`find_recent_errors`. Plus the plugin-action triplet
(`list_plugin_actions`, `invoke_plugin_action`,
`await_streaming_plugin_action`) from Phase 4a/4b, which slots into
the same read-leaning surface.

Setup helper shipped: `hc-mcp setup` ✅
Provisions an API key against a running homeCore. Two auth paths:
`--admin-token <jwt>` (or `HC_ADMIN_TOKEN` env) for an existing JWT,
or `--username/--password` to log in via /auth/login first. Issues a
key with the Phase 1 + plugin-action scope set by default, writes
the resulting config.toml at 0600. `--rotate` re-issues; `--force`
overwrites without rotating (manual paste flow).

Outstanding for Phase 1:
- `mqtt_tap(topic_filter, duration_secs)` — needs a persistent
  paho-MQTT client. Defer to Phase 4 (mqtt_tap was always part of the
  "advanced" tier).

### Phase 2 — Device + rule operations ✅ (shipped 2026-05-01)
Tools live: `command_device`, `bulk_command` (write category
`device_commands`); `enable_rule`, `disable_rule`, `delete_rule`,
`create_rule`, `update_rule` (write category `rule_mutations`). All go
through the homeCore REST API so they work universally regardless of
install method (local / docker / remote). Existing
`permissions.ensure_write(category)` mechanism reused — operator opts
in via `HC_MCP_ALLOW_WRITE=device_commands,rule_mutations` (or `all`).

### Phase 3 — Plugin scaffolding (~2 days)
- `scaffold_plugin` for Rust (biggest template set), others later
- `check_plugin`, `add_management_action` (~6 tools + template set)
- Templates exercised against SDK patterns from memory notes

### Phase 4 — Advanced (~2 days)
- `mqtt_tap`, `rule_graph`, anomaly detection, `audit_acls`, migration helpers (~10 tools)
- Persistent MQTT connection pool

---

## Start point

**Phase 1 only** — plan recommends this. Gives immediate troubleshooting
value with no write risk. ~1-2 days of work total.

---

## Resolved decisions

### 1. Transport — both stdio + HTTP/SSE from day one
- MCP Python SDK supports both with a flag; marginal extra code.
- **Phase 1: stdio + HTTP/SSE bound to `127.0.0.1` only.** No public exposure.

### 2. Auth — homeCore API key (long-lived bearer token)  *(updated 2026-04-29)*
homeCore now has dedicated API keys (`POST /api/v1/auth/api-keys`),
which superseded the password-login + JWT-refresh flow originally
planned here. hc-mcp stores a single `api_key` in
`~/.config/hc-mcp/config.toml` (or via the `HC_MCP_API_KEY` env var)
and attaches it as `Authorization: Bearer <key>` on every request.

Properties:
- Long-lived. Survives core restarts (no JWT-secret-rotation worry).
- Audit-friendly. Each key has a name and a creator user; logs show
  the key id as the actor.
- Revocable. Rotate via `POST /api/v1/auth/api-keys/{id}/rotate`
  (or delete and re-issue) without restarting hc-mcp.
- Role-scoped. Issue with `role = ReadOnly` for Phase 1; flip to
  `User` when Phase 2 (write tools) lands.

**Setup helper (still TODO — see Phase 1 leftovers):** `hc-mcp setup`
that walks an admin through generating a key against their core, with
an idempotent re-run that rotates it on demand.

### 3. Remote access — local-only in Phase 1
Revisit in Phase 2. Three tiers considered, in increasing effort:
- **Local only (Phase 1):** stdio + loopback HTTP/SSE. No remote surface.
- **VPN overlay (Phase 2):** bind on Tailscale IP; trust tailnet identity;
  MCP still bearer-auths at HTTP layer. Zero new crypto, realistic for homelab.
- **Public TLS + OAuth 2.1 (later, maybe never):** MCP spec supports it;
  heavy — cert + OAuth flow. Only if hc-mcp goes off-LAN without a VPN.

### Core auth facts that shape this design  *(updated 2026-04-29)*
- API keys are the canonical service-account credential. Long-lived,
  hashed at rest in core's state store, bearer-auth via the same
  middleware as JWTs.
- JWT login + refresh tokens also exist (`/auth/login` returns a JWT
  + refresh token; `/auth/refresh` rotates both). Suited to
  human-driven UI clients — hc-mcp uses keys instead so a long-running
  agent doesn't need refresh logic.
- Roles: `Admin` / `User` / `ReadOnly` (and 7 preset variants per the
  expanded auth model). API keys inherit the issuer's role at creation.
- An IP whitelist in core config grants Admin bypass for specific
  CIDRs — useful fallback for trusted-network deployments where running
  hc-mcp against `127.0.0.1` and the whitelist makes the api-key step
  optional. Broader than ideal for an audited service account though.
