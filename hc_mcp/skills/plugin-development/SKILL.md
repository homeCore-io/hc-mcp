---
name: plugin-development
description: Guides writing, testing and releasing a homeCore plugin in Rust, Python, JavaScript (Node) or .NET. Covers registering devices with a schema, the shared device vocabulary (names and units), commands, plugin actions (immediate and streaming, requires_role including signed_in, the verified caller), settings forms, notices and alerts, the plugin's own REST access (api_scopes and api_access), plugin screens and cards (ui/ folder, slots, the host API), files sent to actions, testing on a sandbox with stand-in devices, and CI and releases to the plugin registry (signed index, Python runtime artifacts). Use when someone asks to write a homeCore plugin, contribute one or change an SDK, add a device type or attribute, add a plugin action, build a plugin screen or card, debug a plugin that hangs or dies, or release a plugin.
license: MIT OR Apache-2.0
---

# homeCore plugin development

A homeCore plugin is a separate process that bridges a hub, cloud service or
protocol into homeCore. It talks MQTT to homeCore's broker through an SDK:
it registers devices with a schema and publishes their state, receives
commands, answers homeCore's management channel (heartbeat, settings, log
level, its own actions), may raise alerts, and may carry its own screens.
homeCore starts it with its config file's path as the only argument,
restarts it with backoff when it exits, and owns that config file.

The full guide is
[Developing Plugins](https://homecore.io/docs/plugins/developing-plugins).
When a page and the code disagree, the code wins: the SDK sources and the
types in `crates/hc-types` of the [homeCore repository](https://github.com/homeCore-io/homeCore).

## 1. Pick a language

| Language | SDK | Catalog release | Read |
|---|---|---|---|
| Rust | `plugin-sdk-rs`, in the homeCore repo at `sdk/rust` | yes, native binary | [references/rust.md](references/rust.md) |
| Python | `homecore-plugin-sdk` ([hc-plugin-sdk-py](https://github.com/homeCore-io/hc-plugin-sdk-py)) | yes, runs in a plugin runtime | [references/python.md](references/python.md) |
| JavaScript | `homecore-plugin-sdk` ([hc-plugin-sdk-js](https://github.com/homeCore-io/hc-plugin-sdk-js)) | yes, runs in a plugin runtime (pure JavaScript) | [references/javascript.md](references/javascript.md) |
| .NET | `HomeCore.PluginSdk` ([hc-plugin-sdk-dotnet](https://github.com/homeCore-io/hc-plugin-sdk-dotnet)) | not yet | [references/dotnet.md](references/dotnet.md) |

Nothing is published to crates.io, PyPI, npm or NuGet. Install each SDK from
its GitHub repository at a tag (Rust: a homeCore release tag), and check the
SDK's README for the current install method. Each language reference has a
minimal working plugin, a table of the SDK's names for every concept below,
and how to run and test it.

Only Rust has pictures the plugin keeps (`with_files_dir`), async action
handlers, and reading other devices' availability and schemas. Rust and
JavaScript (SDK 0.4.7) take files sent to actions. .NET has no release path to
the Catalog: choose Rust, Python or JavaScript if the plugin must be
installable from it.

## 2. Start from a working plugin

- **Rust:** copy `plugins/hc-plugin-template` in the homeCore repository to
  `plugins/hc-<name>`, rename the crate, binary and plugin id
  (`plugin.<name>`), and add it to the workspace members. Read its
  `src/main.rs` top to bottom; the comments are the startup contract.
- **Other languages:** start from the minimal plugin in the language
  reference.
- Larger examples: `plugins/hc-wled` (alerts, uploads, named numbers,
  screens, a step form, cards), `plugins/hc-ecowitt` (a Svelte page, panel
  and cards), `plugins/hc-captest` (one demo of each action pattern), and
  [hc-mcp](https://github.com/homeCore-io/hc-mcp) (a Python plugin with an
  assistant panel).

Every plugin's config has the same `[homecore]` table, which homeCore fills
in when it installs the plugin:

```toml
[homecore]
broker_host = "127.0.0.1"
broker_port = 1883
plugin_id   = "plugin.demo"
password    = ""
```

## 3. Startup order

```text
read config (argv[1]) → logging → connect → enable management
  + capability manifest (actions, api_scopes) + settings schema/descriptor
  + alert kinds + UI dir + stop handler
→ start the event loop → register devices, schema, subscribe → publish state
```

- **Rust: start the event loop before registering anything.** Until
  `run_managed` polls, publishes only queue (64 messages, about four per
  device), and a plugin with a dozen devices hangs at startup with no error.
  The other SDKs register from their `on_connect` hook, after the loop runs.
- **Call management setup once.** In Python, JavaScript and .NET,
  `on_connect` runs again on every reconnect, and each management call
  starts another heartbeat. Guard it with a flag.
- **Stopping is the SDK's job.** homeCore stops a plugin with SIGTERM and
  kills it 2 seconds later. The SDK runs your stop handler (1 second: leave a
  heater off, sign out), marks every device offline, reports the plugin
  offline and exits. Never install your own SIGTERM handler. The SDKs also
  exit when the homeCore that started them is gone (`HOMECORE_SUPERVISED`).

## 4. Devices: register, publish, command

1. **Register** each device with a `device_type` (what it is, never the
   protocol: `light`, `switch`, `sensor`, `thermostat`, `lock`, `cover`,
   `media_player`, `scene`, ...). Clients choose cards and controls by it.
2. **Send a schema.** A device without one is a row of raw JSON nobody can
   operate. Each attribute gets `kind`, `writable`, `unit`, `min`/`max`,
   `display_name`; booleans name both states; housekeeping readings are
   `category: "diagnostic"`; an integer that is a choice gets named
   `options`; device actions get a `sentence` (`"toggle {device}"`).
3. **Subscribe to its commands.** In Rust this is a separate call
   (`subscribe_commands`), and forgetting it is the classic first bug. The
   other SDKs subscribe when you register.
4. **Publish the whole state once** (retained), then partials. Publish
   availability, and set it again when you lose or regain the device.
5. **Handle commands** in exactly two shapes: a write to a writable
   attribute, `{"on": true}`, or a declared action,
   `{"action": "toggle", ...}`. Hand slow device I/O to a worker so it
   never stalls the MQTT loop. Publish what the device confirms, with the
   SDK's `_for_command` variant so the change records its cause.

Registration is not retained: every device shares the plugin's one `register`
topic, and a broker keeps only the last retained message per topic. Register
again on every reconnect instead (the SDKs do).

**Removing devices.** A device stays in homeCore until the plugin unregisters
it, and a plugin unregister is a hard delete: no undo, and rules that name the
device keep a dead reference. So retire a device only on an authoritative
answer that it is gone: the hub's own inventory after a complete, successful
read (Rust: `with_device_persistence` plus `reconcile_devices(live)`). Silence
is not that answer. A sensor with a flat battery is silent too, and removing
it loses its room and breaks its rules. If the source can only say what it
heard, never reconcile against that; find the inventory it keeps (hc-ecowitt
reads the gateway's paired-sensor slots and waits a day) or leave removal to
the person, in Settings › Devices.

State rules: never publish a value that changes by itself on every refresh
(uptime, a clock), since every publish is a state-changed event. Publish
`null` rather than dropping a key you sometimes can't read. Read and write
the same name.

**Names and units:** use the shared vocabulary whenever the idea matches
(`on`, `brightness_pct` 0 to 100, `color_temp` kelvin, `transition_ms`,
`position` with 100 open, `open` true when open, `battery_pct`, temperatures
in °C, ...), and convert from the device's scale inside the plugin, with a
test at each end of the scale. Read
[references/device-vocabulary.md](references/device-vocabulary.md) before
naming any attribute.

A camera keeps its newest picture in its files folder, names it in a
`snapshot` attribute (a new name each time), and takes a fresh one on a
`take_snapshot` action; then a rule's Notify step can send the picture.

## 5. Plugin actions

Actions the plugin itself offers (pair, rescan, install firmware) go on the
**capability manifest**, each with a label, description, params schema,
`requires_role` and `timeout_ms`. Immediate actions reply once; streaming
actions (`stream: true`) emit `progress`, `item`, `awaiting_user`, `warning`
and one terminal `complete` or `error` (or `canceled`).

- `requires_role` is `user` (default; needs `plugins:write`), `read_only`
  (also answers on `/query` for anyone who can read devices), `admin`, or
  `signed_in` (anyone signed in, a household member included). `signed_in`
  is opt-in: use it only for an action safe for everyone, or one that limits
  itself by `caller`.
- Every forwarded action carries the verified `caller`
  (`uid`, `username`, `role`, `scopes`, `kind`). Do for a caller only what
  their `scopes` allow.
- A manifest with `api_scopes` gets the plugin its own API key on every
  start, sent as the `api_access` management action (`url`, `key`,
  `scopes`). Every SDK answers it for you and keeps the grant (Rust from
  SDK 0.6.5).
- Always set `timeout_ms`. Core's default is 5 seconds.

Details, stage rules, and where each SDK puts `caller`:
[references/actions.md](references/actions.md).

## 6. Settings

A plugin's settings are its TOML file, which homeCore owns and restarts the
plugin on. Declare a **config schema** (in Rust, derived from the config
structs with `schemars`, so it can't drift) and a **config descriptor**
(sections, field kinds, help) on the manifest, and the web app draws a form
that writes only what changed. Rust: keep the template's coverage test
(`config_descriptor::missing_schema_coverage`) so a new setting can't be
left out of the form. Python, JavaScript and .NET pass a form's changes to
your `on_set_config` hook to write; they have no TOML writer. Paths in the
config are relative to the config file's folder unless absolute. A plugin
has no unit setting: units are the app's job.

See [Configuration: schema and descriptor](https://homecore.io/docs/plugins/developing-plugins#configuration-schema-and-descriptor).

## 7. Notices and alerts

- **Notices** are about the plugin itself ("no devices configured", "can't
  reach the hub"), shown on its page with a remedy. A notice is state:
  raise it while the condition holds and clear it when it stops, after every
  sync, reconnect and config change.
- **Alerts** are about its devices, in the house's alert list. Declare the
  kinds on the manifest (topic, label, severity, `default_on`), then call
  `set_alerts(device_id, [...])` with the whole list of what is true now;
  one you stop sending has cleared. An alert can carry a button (a device or
  plugin action, with params and `confirm`). Plugins can't raise critical
  alerts, and news that isn't a problem is `default_on: false`.

See [Alerts from Plugins](https://homecore.io/docs/plugins/plugin-alerts).

## 8. Screens and cards

A plugin can carry web components that the app puts in slots:
`plugin.page`, `device.panel`, `rule.step`, `device.card`,
`dashboard.card`, `look.drawing`, `look.piece`, `look.symbol` and
`app.assistant`. Build them into one ES module plus `manifest.json` in
`ui/dist`, and declare the folder with the SDK's `with_ui_dir`. The plugin
serves the files; homeCore passes them through; the app falls back to its
generic screens when they are missing. Each element gets a `host` scoped to
the plugin.

Read [references/screens.md](references/screens.md) for the slots' contracts,
the `host` API, building, and the gotchas.

## 9. Testing: a sandbox and stand-ins, never a real house

- **Unit tests** beside the code. Test conversions at both ends of the
  scale, every writable attribute, and that every declared action is handled
  and every handled action declared (Rust: `plugin_sdk_rs::conformance`).
  Test against payloads copied from real devices, with secrets scrubbed.
- **A sandbox homeCore**: its own home folder, config, API port and broker
  port, so nothing touches a running house.

  ```bash
  # in the homeCore repository; the sandbox config sets its own [server] port and [broker] port
  cargo run -p homecore -- --home /tmp/hc-sandbox --config /tmp/hc-sandbox/config/homecore.toml
  ```

  Point the plugin's `[homecore]` at the sandbox broker and run it by hand,
  or give the sandbox a `[[plugins]]` entry (`id`, `binary`, `config`) so it
  supervises the plugin. To prove the release layout, install a built package
  with `POST /api/v1/plugins/install` and `{"path": "/abs/plugin.tar.zst"}`.
- **Stand-ins**: small local programs that answer like the device, so the
  plugin has something to talk to. For an HTTP device:

  ```python
  # standin.py: answers GET /json/state like a lamp, on 127.0.0.1:8099
  import json
  from http.server import BaseHTTPRequestHandler, HTTPServer

  STATE = {"on": True, "bri": 128}

  class Lamp(BaseHTTPRequestHandler):
      def do_GET(self):
          body = json.dumps(STATE).encode()
          self.send_response(200)
          self.send_header("Content-Type", "application/json")
          self.end_headers()
          self.wfile.write(body)

  HTTPServer(("127.0.0.1", 8099), Lamp).serve_forever()
  ```

- **Never test against a real house.** No discovery from a sandbox (it finds
  real devices), no commands to real devices, and real devices only for
  read-only requests to copy their payload shapes.
- **Screens:** drive the web app against the sandbox in a headless browser;
  check desktop and phone widths, light and dark, and the fallback with the
  plugin stopped.
- **Restart behavior:** restart the sandbox homeCore and its broker while the
  plugin runs, and stop the plugin with SIGTERM. Devices should go offline
  and come back.

## 10. CI and releasing

Rust plugins call the shared `rust-ci.yml`; every caller needs
`permissions: {contents: read, issues: write}`. A release is one tag after
CI is green: `hc-<name>-v<version>` for a plugin in the homeCore repository,
`v<version>` for a Python or Node.js plugin in its own repository. The shared
workflow builds the package (a static binary plus `ui/`, a Python wheelhouse,
or a Node.js app with its `node_modules`), starts it against a broker, attaches
it to a GitHub Release and notifies the registry, whose signed index homeCore
installs from. Catalog name, category and description come from the package
metadata. Read [references/releasing.md](references/releasing.md).

## 11. Contributing a plugin, or a change to an SDK

A plugin can run in four places. Prefer the first two.

| Where | Language | Catalog |
|---|---|---|
| In the homeCore repository (`plugins/hc-<name>`), started by homeCore | Rust | yes, released by maintainers |
| In a plugin runtime, from its own repository | Python, Node.js | once a maintainer lists it |
| Its own package, started by homeCore | Rust | once listed |
| A service run outside homeCore (a container, Kubernetes, a microcontroller) | any | no |

A plugin from outside homeCore-io releases with `publish_registry: false`,
since notifying the registry needs an organization secret, and then asks for
a listing on [homeCore-io/registry](https://github.com/homeCore-io/registry/issues).

A service outside homeCore connects with a `[[broker.clients]]` login whose
`id` is its plugin id, keeps its own settings (homeCore holds no config file
for it), sets a Last Will, and appears under Settings › Plugins once it sends
a heartbeat. Use an SDK for it if you can.

**An SDK change has to work for every plugin**, not the one deployment it was
written for: many devices as well as one; started by homeCore, in a runtime
or on its own.

- A new way to send something sends what the existing call sends. A
  heartbeat carries `sdk_version`, `device_count` and the rest core reads; a
  capability manifest goes through the manifest builder, so the settings
  schema, descriptor, alert kinds and screens aren't dropped (and since it is
  retained, a thin one replaces the full one).
- The protocol (topics, payloads, what is retained) is shared by every plugin
  and homeCore. Change it only after an issue agrees.
- Respect the caller's options: don't quietly override what they set (a
  clean session, a keep-alive).
- In async Rust, never hold a lock or a `watch::Ref` across an `.await`:
  bind the value to a local first.
- Test the new calls, say which plugins use them, and say whether the other
  SDKs need the same change.

See [Contributing](https://homecore.io/docs/development/contributing#contributing-a-plugin).

## The rules most often broken

1. **Screens ship with the plugin.** The plugin carries `ui/` and serves it;
   the web app holds no plugin-specific code. Never add a plugin's screen to
   the app: give the plugin a slot.
2. **Screens use only `host`**, never the app's internals. Check for
   members added later before using them.
3. **Name numbered choices in the schema** (`options` on an integer
   attribute) instead of writing a screen or special-casing the app.
4. **Shared ideas use the shared names and units**, converted at the edge.
   Commands are an attribute write or `{"action": ...}`, never
   `{"command": ...}`.
5. **Never test against a real house.** Sandbox homeCore, stand-in devices.
6. **Never die silently.** A plugin that can't do its job says so: a notice
   while it retries, then a log line naming the cause and a non-zero exit,
   so the supervisor shows why and restarts it with backoff. A plugin whose
   event loop has stopped must exit, never sit there looking healthy.
   Retry the first connection a few times, then exit.
7. **Notices and alerts are current state**, cleared when no longer true.
8. **Every action declares `timeout_ms`**, and nothing slow runs on the
   MQTT loop: Rust answers device-bound actions with `with_async_handler`;
   the other SDKs use a streaming action or a worker thread.

## Before you call a plugin done

- [ ] Starts cleanly, survives homeCore and the broker restarting, and goes
      offline on SIGTERM.
- [ ] Every device has a `device_type` and a schema; choices have named
      options; device actions have sentences.
- [ ] Shared names and units, converted at the edge, tested at both ends.
- [ ] Nothing it publishes changes by itself every refresh.
- [ ] It removes a device only when the source's own inventory says it is
      gone, never because it went quiet.
- [ ] Settings have a schema and a descriptor (and, in Rust, the coverage
      test passes).
- [ ] Alerts are current state; news is `default_on: false`.
- [ ] Screens fall back cleanly, look right at phone width in light and dark,
      and use only `host`.
- [ ] Tested on a sandbox with stand-ins.
- [ ] README: what it publishes, its commands, actions, alerts, settings and
      screens.

## Further reading

- [Developing Plugins](https://homecore.io/docs/plugins/developing-plugins): the long version of everything above, raw MQTT topics, and the pre-release checklist
- [Plugin Capabilities & Actions](https://homecore.io/docs/plugins/capabilities)
- [Plugin Screens and Cards](https://homecore.io/docs/plugins/plugin-screens)
- [Alerts from Plugins](https://homecore.io/docs/plugins/plugin-alerts)
- [Plugin Runtimes](https://homecore.io/docs/plugins/runtimes)
- [Contributing](https://homecore.io/docs/development/contributing): the ways to contribute a plugin, getting listed, and running your own registry
