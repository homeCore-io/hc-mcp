# hc-mcp — Design Plan

> Model Context Protocol server for homeCore. Written in Python using the
> official Anthropic `mcp` SDK. Exposes typed tools Claude can call for
> troubleshooting, rule creation, plugin scaffolding, and more.

**Status:** design phase. No code yet. Pick up here to scaffold the repo + Phase 1.

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

### Phase 1 — Read-only troubleshooter (~1-2 days)
- Repo scaffold: `pyproject.toml`, `mcp` SDK dep, server entry, auth plumbing
- Transport: stdio first, HTTP/SSE follow-up
- Tools: `system_health`, `plugin_status`, `plugin_logs`, `core_logs`,
  `device_state`, `device_history`, `rule_firings`, `find_recent_errors`,
  `correlation_trace` (~15 tools)
- Zero write risk. Immediate value for troubleshooting (e.g. current
  thermostat debugging workflow).

### Phase 2 — Device + rule operations (~1 day)
- `list_devices`, `command_device`, `list_rules`, `create_rule`, `test_rule`,
  `enable_rule`, `disable_rule`, `bulk_command` (~10 tools)
- Introduce write-category gating

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

## Resolved decisions (2026-04-20)

### 1. Transport — both stdio + HTTP/SSE from day one
- MCP Python SDK supports both with a flag; marginal extra code.
- **Phase 1: stdio + HTTP/SSE bound to `127.0.0.1` only.** No public exposure.

### 2. Auth — dedicated `mcp-service` user, credentials-based
homeCore has no API keys or long-lived tokens today (see "Core auth facts"
below). So hc-mcp stores **username + password** and re-logs in on startup
and on any 401.

**Account creation:** a `hc-mcp setup` command that:
- Prompts for an admin JWT (or `--admin-token`) and core URL.
- Generates a random password.
- `POST /api/v1/auth/users` with `username=mcp-service`, generated password,
  `role=ReadOnly` (Phase 1).
- Writes credentials to `~/.config/hc-mcp/config.toml` (chmod 600).
- Idempotent: rerun with `--grant-write` flips the role to `User` for Phase 2+.

### 3. Remote access — local-only in Phase 1
Revisit in Phase 2. Three tiers considered, in increasing effort:
- **Local only (Phase 1):** stdio + loopback HTTP/SSE. No remote surface.
- **VPN overlay (Phase 2):** bind on Tailscale IP; trust tailnet identity;
  MCP still bearer-auths at HTTP layer. Zero new crypto, realistic for homelab.
- **Public TLS + OAuth 2.1 (later, maybe never):** MCP spec supports it;
  heavy — cert + OAuth flow. Only if hc-mcp goes off-LAN without a VPN.

### Core auth facts that shape this design
- JWTs are short-lived (default 24h via `[auth].token_expiry_hours`).
- **No refresh tokens, no API keys.** Re-login with credentials is the only renewal path.
- JWT signing secret regenerates on every core restart unless explicitly configured,
  invalidating all tokens. hc-mcp must treat restarts as implicit session loss —
  re-login on 401, don't cache tokens across core outages.
- Roles are coarse: `Admin` / `User` / `ReadOnly`. No per-scope custom roles.
- An IP whitelist in core config grants Admin bypass for specific CIDRs —
  available as a fallback if credentials flow proves painful, but it's broader
  than we want for an audited service account.

Expanding core auth (API keys / service accounts / token persistence) is
tracked as a separate discussion — if that lands, hc-mcp switches to API keys
and drops the password-login path.
