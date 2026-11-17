# Rust plugins

Read this when the plugin is in Rust. The SDK is the crate `plugin-sdk-rs`
(0.6.5 at the time of writing). It lives at `sdk/rust` in the
[homeCore repository](https://github.com/homeCore-io/homeCore), and every
first-party Rust plugin lives beside it at `plugins/hc-<name>` as a workspace
member. Its README is the API reference; this page is the working minimum.

## Install

The crate is not on crates.io.

- **Inside the homeCore repository** (the usual case), depend by path. An SDK
  edit then reaches every plugin on the next build, and the repo-root
  `cargo fmt`, `clippy` and `test` cover core, the SDK and all plugins:

  ```toml
  [dependencies]
  plugin-sdk-rs = { path = "../../sdk/rust" }
  tokio         = { version = "1", features = ["full"] }
  serde         = { version = "1", features = ["derive"] }
  serde_json    = "1"
  toml          = "1"
  anyhow        = "1"
  tracing       = "0.1"
  tracing-subscriber = { version = "0.3", features = ["env-filter", "fmt", "registry"] }
  ```

- **Outside it**, pin a core release tag (the SDK re-exports core's
  `hc-types`, which is the plugin ABI, so an unpinned dependency changes
  under you). Use the newest `v0.1.x` tag on the homeCore repository:

  ```toml
  plugin-sdk-rs = { git = "https://github.com/homeCore-io/homeCore", tag = "v0.1.<n>" }
  ```

Check `sdk/rust/README.md` for the current method before you start.

## Start from the template

Copy `plugins/hc-plugin-template` to `plugins/hc-<name>`, rename the crate,
binary and plugin id (`plugin.<name>`), and add it to the workspace `members`
in the root `Cargo.toml`. The release derives the plugin id from the binary
name (`hc-<name>` becomes `plugin.<name>`), so keep them matched. The
template's `src/main.rs` comments are the startup contract; its `config.rs`
has the config schema, the descriptor and the coverage test.

For more complete examples, read `plugins/hc-wled` (alerts, uploads, named
numbers, screens, a step form, cards) and `plugins/hc-ecowitt` (a Svelte
page, panel and cards). `plugins/hc-captest` has one demo of each streaming
pattern.

## A minimal plugin

One lamp: an immediate `signed_in` action that reads `caller`, an admin
streaming action, REST access, an alert kind, a stop handler and its own
screens. It compiles against SDK 0.6.5 and passes its conformance test.

`config/config.toml.example`:

```toml
[homecore]
broker_host = "127.0.0.1"
broker_port = 1883
plugin_id   = "plugin.demo"
password    = ""
```

`src/main.rs` (crate `hc-demo`, so its log filter names `hc_demo`):

```rust
use std::collections::HashMap;

use anyhow::{Context, Result};
use plugin_sdk_rs::device_actions::{with_actions, Action as DeviceAction};
use plugin_sdk_rs::types::schema::{
    AttributeKind, AttributeSchema, BoolStates, DeviceSchema, StateLabel,
};
use plugin_sdk_rs::types::{
    Action, AlertSeverity, Capabilities, Concurrency, PluginAlert, PluginAlertKind, RequiresRole,
};
use plugin_sdk_rs::{Caller, PluginClient, PluginConfig, StreamingAction};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::sync::mpsc;
use tracing::{error, info, warn};

#[derive(Deserialize)]
struct Config {
    homecore: HomeCore,
}

#[derive(Deserialize)]
struct HomeCore {
    #[serde(default = "localhost")]
    broker_host: String,
    #[serde(default = "mqtt_port")]
    broker_port: u16,
    plugin_id: String,
    #[serde(default)]
    password: String,
}
fn localhost() -> String {
    "127.0.0.1".into()
}
fn mqtt_port() -> u16 {
    1883
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter("hc_demo=info,plugin_sdk_rs=info")
        .init();
    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "config/config.toml".into());
    if let Err(e) = run(&config_path).await {
        // Never die quietly: say why and exit non-zero, so the supervisor
        // records the failure and restarts the plugin with backoff.
        error!(error = %e, "plugin failed");
        std::process::exit(1);
    }
}

async fn run(config_path: &str) -> Result<()> {
    let text = std::fs::read_to_string(config_path)
        .with_context(|| format!("could not read {config_path}"))?;
    let cfg: Config = toml::from_str(&text).context("could not parse the config")?;

    let client = PluginClient::connect(PluginConfig {
        broker_host: cfg.homecore.broker_host,
        broker_port: cfg.homecore.broker_port,
        plugin_id: cfg.homecore.plugin_id,
        password: cfg.homecore.password,
    })
    .await?;
    let publisher = client.device_publisher();
    let notices = client.notices();

    let mut mgmt = client
        .enable_management(
            60,
            Some(env!("CARGO_PKG_VERSION").into()),
            Some(config_path.into()),
            None,
        )
        .await?
        .with_capabilities(capabilities())
        .with_alert_kinds([PluginAlertKind {
            topic: "lamp_hot".into(),
            label: "Lamp running hot".into(),
            description: None,
            severity: AlertSeverity::Warning,
            default_on: true,
        }])
        // The SDK answers api_access and keeps the grant; this hook hears
        // each new key (one per start). Read it later with
        // `mgmt.api_access()` and call `{url}/...` with
        // `Authorization: Bearer {key}`.
        .with_api_access_handler(|access| {
            info!(url = %access.url, scopes = access.scopes.len(), "REST access");
        })
        .with_custom_handler(move |cmd| match cmd["action"].as_str()? {
            // A signed_in action: core verified `caller`, so judge by its scopes.
            "whoami" => {
                let caller = Caller::from_cmd(cmd).unwrap_or_default();
                Some(json!({
                    "status": "ok",
                    "username": caller.username,
                    "can_command": caller.has_scope("devices:command"),
                }))
            }
            _ => None,
        })
        .with_streaming_action(StreamingAction::new("scan", |ctx, _params| async move {
            for i in 0..3u8 {
                if ctx.is_canceled() {
                    return ctx.canceled().await;
                }
                ctx.progress(Some(i * 33), Some("scanning"), None).await?;
                ctx.item_add(json!({ "id": format!("lamp-{i}") })).await?;
            }
            ctx.complete(json!({ "found": 3 })).await
        }))
        .with_stop_handler(|| async { info!("stopping") });
    if let Some(dir) = plugin_sdk_rs::ui::find_dir(env!("CARGO_MANIFEST_DIR")) {
        mgmt = mgmt.with_ui_dir(dir, env!("CARGO_PKG_VERSION"));
    }

    // Start the event loop BEFORE registering anything: until it polls,
    // publishes only queue (64 of them) and a larger plugin hangs at startup.
    let (tx, mut rx) = mpsc::channel::<(String, Value)>(64);
    tokio::spawn(async move {
        let on_command = move |id: String, payload: Value| {
            if tx.try_send((id, payload)).is_err() {
                warn!("command queue full, dropped");
            }
        };
        if let Err(e) = client.run_managed(on_command, mgmt).await {
            error!(error = %e, "event loop stopped");
        }
        // Dropping `tx` here ends the command loop below, so the process exits.
    });

    let id = "demo_lamp";
    publisher
        .register_device_full(id, "Demo Lamp", Some("light"), None, None)
        .await?;
    publisher
        .register_device_schema_json(id, &with_actions(&schema(), device_actions()))
        .await?;
    publisher.subscribe_commands(id).await?; // separate from registering
    let mut lamp = Lamp {
        on: false,
        pct: 100.0,
    }; // stands in for the real device
    publisher.publish_state(id, &lamp.state()).await?;
    publisher.publish_availability(id, true).await?;
    // A notice is state: raise it while the problem holds, clear it after.
    notices.clear("lamp_unreachable");

    while let Some((device_id, cmd)) = rx.recv().await {
        if let Err(e) = lamp.apply(&cmd) {
            warn!(error = %e, "command refused");
            continue;
        }
        publisher
            .publish_state_partial_for_command(&device_id, &lamp.state(), &cmd, "demo")
            .await?;
        let alerts = if lamp.on && lamp.pct >= 100.0 {
            vec![PluginAlert::new("lamp_hot", "At full power")]
        } else {
            vec![] // the whole list each time; an empty one clears
        };
        publisher.set_alerts(&device_id, &alerts).await?;
    }
    // The event loop is gone: exit non-zero so the supervisor restarts us.
    anyhow::bail!("the event loop stopped")
}

#[derive(Clone, Copy)]
struct Lamp {
    on: bool,
    pct: f64,
}

impl Lamp {
    /// Shared names and units: `on`, `brightness_pct` 0 to 100. Off is 0 %.
    fn state(&self) -> Value {
        json!({ "on": self.on, "brightness_pct": if self.on { self.pct } else { 0.0 } })
    }

    /// The two command shapes: an attribute write, or `{"action": ...}`.
    fn apply(&mut self, cmd: &Value) -> Result<()> {
        if let Some(action) = cmd.get("action").and_then(Value::as_str) {
            match action {
                "toggle" => self.on = !self.on,
                other => anyhow::bail!("unknown action {other}"),
            }
            return Ok(());
        }
        if let Some(on) = cmd.get("on").and_then(Value::as_bool) {
            self.on = on; // `on: true` keeps the last level
        }
        if let Some(pct) = cmd.get("brightness_pct").and_then(Value::as_f64) {
            self.on = pct > 0.0;
            if pct > 0.0 {
                self.pct = pct.min(100.0);
            }
        }
        Ok(())
    }
}

fn schema() -> DeviceSchema {
    let mut attributes = HashMap::new();
    attributes.insert(
        "on".to_string(),
        AttributeSchema {
            kind: AttributeKind::Bool,
            writable: true,
            display_name: Some("Power".into()),
            states: Some(BoolStates {
                when_true: StateLabel::verbed("on", "turns on"),
                when_false: StateLabel::verbed("off", "turns off"),
            }),
            ..Default::default()
        },
    );
    attributes.insert(
        "brightness_pct".to_string(),
        AttributeSchema {
            kind: AttributeKind::Float,
            writable: true,
            display_name: Some("Brightness".into()),
            unit: Some("%".into()),
            min: Some(0.0),
            max: Some(100.0),
            step: Some(1.0),
            ..Default::default()
        },
    );
    DeviceSchema {
        attributes,
        ..Default::default()
    }
}

fn device_actions() -> Vec<DeviceAction> {
    vec![DeviceAction::new("toggle")
        .label("Toggle")
        .icon("power")
        .sentence("toggle {device}")]
}

fn capabilities() -> Capabilities {
    let action = |id: &str, label: &str, role, stream| Action {
        id: id.into(),
        label: label.into(),
        description: Some(format!("{label}.")),
        params: None,
        result: None,
        stream,
        cancelable: stream,
        concurrency: Concurrency::Single,
        item_key: stream.then(|| "id".into()),
        item_operations: None,
        requires_role: role,
        timeout_ms: Some(30_000),
        danger: false,
    };
    Capabilities {
        spec: "1".into(),
        plugin_id: String::new(), // the SDK fills it in
        actions: vec![
            action("whoami", "Who am I", RequiresRole::SignedIn, false),
            action("scan", "Scan for lamps", RequiresRole::Admin, true),
        ],
        api_scopes: vec!["devices:read".into()],
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_declaration_follows_the_rules() {
        plugin_sdk_rs::conformance::check_all(&super::schema(), &super::capabilities()).assert_ok();
        plugin_sdk_rs::conformance::check_actions_routed(
            &super::capabilities(),
            &["whoami", "scan"],
        )
        .assert_ok();
    }
}
```

What to notice:

- `run_managed` is spawned **before** any registration. Until it polls,
  publishes queue (64 messages, about four per device) and a plugin with a
  dozen devices hangs at startup with no error.
- `register_device_full` and `subscribe_commands` are separate calls.
  Forgetting the second is the classic first bug: state updates, commands go
  nowhere.
- Commands arrive on a synchronous callback. Hand them to a channel so slow
  device I/O never stalls the MQTT loop.
- The SDK answers `api_access` itself (since 0.6.5) and keeps the grant:
  `mgmt.api_access()`, `mgmt.wait_for_api_access(timeout)` (on a task of its
  own, once `run_managed` is running), `mgmt.api_access_updates()`, and the
  hook `with_api_access_handler`. Clone the handle before `run_managed`
  takes it; every clone sees the same grant. A custom handler that still
  answers `api_access` keeps working, and its reply is what core gets.
- In the custom handler, `cmd` is the whole management message: the action's
  params and `caller` sit at its top level (`Caller::from_cmd(cmd)` reads
  it). A streaming handler's `params` is the same message without `action`,
  `request_id` and `caller`; it reads the caller with `ctx.caller()`.
- When the event loop ends, `run` returns an error and `main` exits 1.

## The SDK's names

| Concept | Rust SDK |
|---|---|
| Connect | `PluginClient::connect(PluginConfig { broker_host, broker_port, plugin_id, password })` |
| Remember devices across restarts | `.with_device_persistence(path)`, then `publisher.reconcile_devices(live)` after a sync you trust |
| Handles (take before the loop) | `client.device_publisher()`, `client.notices()` |
| Management | `client.enable_management(heartbeat_secs, Some(version), Some(config_path), log_handle)` returns a `ManagementHandle` |
| Event loop | `client.run_managed(on_command, mgmt)`; `run_managed_with_state` for reading other devices |
| Register | `register_device_full(id, name, Some(device_type), area, capabilities)`; `register_device_typed`; `register_device_detailed` with `DeviceHardware` |
| Schema | `register_device_schema(id, &DeviceSchema)` or `register_device_schema_json(id, &Value)`; `device_actions::with_actions(&schema, actions)` adds device actions |
| Subscribe to commands | `subscribe_commands(id)` |
| State | `publish_state` (whole, retained), `publish_state_partial` (merge patch), and `_for_command` / `_with_change` variants that record what caused the change |
| Availability | `publish_availability(id, online)` |
| Capability manifest | `.with_capabilities(Capabilities { spec: "1", plugin_id: "" (SDK fills it), actions, api_scopes })` |
| Immediate action | `.with_custom_handler(\|cmd\| -> Option<Value>)` (must not block) or `.with_async_handler(\|cmd\| -> Option<AsyncActionFuture>)` for one that talks to a device |
| Streaming action | `.with_streaming_action(StreamingAction::new(id, \|ctx, params\| async move { ... }))` |
| Stages | `ctx.progress(percent, label, message)`, `progress_with_data(.., data)`, `item_add` / `item_update` / `item_remove`, `warning(message, data)`, `awaiting_user` / `awaiting_user_with_schema` / `awaiting_user_with_data` then `await_respond`, `complete`, `error`, `canceled`; `is_canceled()`, `wait_canceled()`. Each event's `ts` is later than the last |
| Roles | `RequiresRole::{Admin, User, ReadOnly, SignedIn}`; `device_actions::Role::SignedIn` on a device action |
| Caller | `Caller::from_cmd(cmd)` (custom and async handlers), `ctx.caller()` (streaming); `caller.has_scope(..)` |
| REST access | `api_scopes` on `Capabilities`; automatic: `mgmt.api_access()` (`ApiAccess { url, key, scopes }`, its `Debug` hides the key), `wait_for_api_access(timeout)`, `api_access_updates()`, hook `with_api_access_handler` |
| Settings | `.with_config_schema(schema)` (derive with `schemars`), `.with_config_descriptor(config_descriptor::Descriptor ... .build())`; coverage test `config_descriptor::missing_schema_coverage` |
| Notices | `notices.raise(PluginNotice::warning(code, msg).with_remedy(..))`, `notices.clear(code)` |
| Alerts | `.with_alert_kinds([PluginAlertKind { .. }])`; `publisher.set_alerts(id, &[PluginAlert::new(topic, reason).key(..).action(..)])`; `set_plugin_alerts` |
| Own screens | `ui::find_dir(env!("CARGO_MANIFEST_DIR"))` then `.with_ui_dir(dir, version)` |
| Pictures it keeps | `.with_files_dir(dir)` (Rust only) |
| Files sent to an action | automatic; the action gets a local `file_path` param (Rust only) |
| Other devices | `subscribe_state`, `subscribe_availability` + `with_availability_handler`, `subscribe_schema` + `with_schema_handler` |
| Stop | `.with_stop_handler(\|\| async { .. })`; the SDK handles SIGTERM itself |
| Log forwarding | `mqtt_log_layer::MqttLogLayer::new()`, then `handle.connect(client.mqtt_client(), plugin_id, level)` |
| House location | `plugin_sdk_rs::house_location()`, `wait_house_location(timeout)` |
| Conformance | `conformance::check_all(&schema, &caps)`, `check_device_schema_json`, `check_writables`, `check_actions_routed`, `check_temperatures`, `check_state_temperatures` |

## Secrets in logs

`MqttLogLayer` publishes log events to a topic anything can read. It redacts
fields whose names contain `password`, `secret`, `token`, `key`, `psk`,
`passcode`, `credential` or `auth`. Pass secrets as named fields, never in
the message text:

```rust
tracing::info!(api_key = %config.api_key, "connecting"); // redacted
```

## Run and test

```bash
# Inside the homeCore repository
cargo test -p hc-<name>                 # unit and conformance tests
cargo clippy -p hc-<name> --all-targets -- -D warnings
cargo fmt --all -- --check
cargo run -p hc-<name> -- plugins/hc-<name>/config/config.toml
```

Run it against a sandbox homeCore, never a real house: see the Testing
section of `SKILL.md`. To let a sandbox homeCore run it, add an entry to the
sandbox config:

```toml
[[plugins]]
id      = "plugin.<name>"
binary  = "/path/to/homeCore/target/debug/hc-<name>"
config  = "config/plugins/plugin.<name>.toml"
enabled = true
```

Keep these tests in every plugin: the conformance test above, a test per
unit conversion at both ends of the scale, `check_writables` for every
writable attribute, `check_actions_routed` for the manifest, and the config
descriptor coverage test from the template's `config.rs`.
