# Configuring homeCore

homeCore reads one TOML file, `homecore.toml`. This page covers how to find and edit it, the sections a new install touches, and the broker and registry settings that most often go wrong.

Public docs: https://homecore.io/docs/getting-started/configuration (every key, with defaults).

## Where the file is

| Install | File |
|---|---|
| Docker | `homecore-data/config/homecore.toml`, seeded by the image on first boot |
| Binary | `homecore/config/homecore.toml`, copied by you from `homecore.toml.example` |

Core picks its home directory from `--home <path>`, then `HOMECORE_HOME`, then the current directory. It picks the config file from `--config <path>`, then `HOMECORE_CONFIG`, then `config/homecore.toml` under the home. Relative paths, both for `--config` and inside the file, resolve against the home.

Other environment variables core reads: `RUST_LOG` (log filter, overrides `[logging]` levels) and `HC_ALLOW_ANONYMOUS_REMOTE_BROKER` (see the broker section below). The Docker entrypoint also reads `HOMECORE_UID`, `HOMECORE_GID` and `HC_BROKER_BIND`.

## How to edit it

**In the app (admins):** **Settings › Configuration**.

- The **Form** tab shows each section with its fields. Change values and press **Save to homecore.toml**.
- The **homecore.toml** tab shows the file itself. **Edit the file…**, change it, **Save homecore.toml**.
- After saving, the page says homeCore reads these when it starts. Press **Restart homeCore…**.

The Settings search box also finds keys inside `homecore.toml` (try "broker" or "port").

**By hand:** edit the file, then restart core (`docker compose restart homecore`, or `sudo systemctl restart homecore`).

Two behaviors to know before editing by hand:

- If the file is missing or fails to parse, core logs a warning and runs on built-in defaults. Those bind the broker to `0.0.0.0` with no logins, which core refuses, so a TOML typo usually shows up as the open-broker error.
- Unknown keys are ignored with no warning. Check spelling against the docs.

**Check it works:** after the restart, the setting shows in **Settings › Configuration** and the change has its effect (for example, the time zone on **Settings › System**).

## Sections a new install sets

| Section | What to set | Notes |
|---|---|---|
| `[location]` | `latitude`, `longitude`, `timezone`, optional `temperature_unit = "°F"` | Used for sunrise and sunset. Without it core uses a default location, so solar rules fire at the wrong times. |
| `[backup]` | `every_hours` (24), `keep` (7), `dir` ("backups") | `every_hours = 0` turns scheduled backups off. Also reachable from **Settings › Data & backups › Change**. |
| `[auth]` | `token_expiry_hours` (24), `refresh_token_expiry_days` (30), `audit_retention_days` (365) | The JWT secret is generated into `data/jwt_secret`; leave `jwt_secret` unset. |
| `[logging]` | `level` and per-output settings | See [maintenance.md](maintenance.md#logs). |
| `[notify]` | `[[notify.channels]]` for email, Pushover or Telegram | Easier from **Settings › Notifications**, which also sends a test. |
| `[alerts]`, `[battery]` | `notify_channel` | Where built-in alerts and low-battery warnings are sent. |

Leave `[server]` (`host = "0.0.0.0"`, `port = 8080`), `[storage]`, `[rules]`, `[profiles]` and `[web_admin]` (off) at their defaults unless there is a reason.

## The MQTT broker (`[broker]`)

Core embeds an MQTT broker. Plugins talk to core through it.

| Key | Default in the shipped config | Meaning |
|---|---|---|
| `host` | `"127.0.0.1"` | Bind address. Loopback keeps it private to the machine. |
| `port` | `1883` | Plain MQTT |
| `v5_port` | `1884` | MQTT v5 listener; `0` turns it off |
| `tls_port`, `cert_path`, `key_path` | unset | Optional TLS listener |
| `external_url` | unset | Use an external broker (Mosquitto) instead of the embedded one |

**When the broker must face the network:** plugin runtimes on other containers or machines, and LAN devices such as Tasmota, Shelly or ESPHome.

The easy way is **Settings › Plugins › Plugin runtimes › Open the broker to the network** (admin). It sets `host = "0.0.0.0"`, adds a login for core itself if there is none, and restarts core. homeCore then makes a login for every runtime and plugin.

By hand, add logins and bind to the network:

```toml
[broker]
host = "0.0.0.0"
port = 1883

[[broker.clients]]
id       = "internal.core"          # always required once any client is listed
password = "<long-random-password>"
allow_pub = ["homecore/#"]
allow_sub = ["homecore/#"]
```

Core refuses to start when `host` is not loopback and no `[[broker.clients]]` exist, so it never runs an open broker. `HC_ALLOW_ANONYMOUS_REMOTE_BROKER=1` overrides that; only use it on a network isolated some other way.

The embedded broker checks the login on connect. It does not enforce the `allow_pub` and `allow_sub` patterns. For per-topic enforcement, run Mosquitto and set `external_url`; see https://homecore.io/docs/administration/broker.

## The plugin registry (`[registry]`)

```toml
[registry]
url        = "https://homecore.io/registry/index.json"
public_key = "<the ed25519 key from the shipped example>"
```

The shipped config already has both. If either is missing, the Catalog cannot load and plugin installs fail with a 503. Core checks the index signature and each artifact's SHA-256 before unpacking anything. Both can point at a private registry (a URL, a local path or `file://`).

## Plugin runtimes (`[plugin_runtimes]`)

`enabled = true` by default. Turning it off makes the runtime endpoints return 404. Older keys from when runtimes asked to join (`mode`, `whitelist_only`) are ignored.

## Plugins blocks

Plugins installed from the Catalog record themselves in `config/plugins/managed.toml`, a file core owns. Core never rewrites `homecore.toml`, and you never add Catalog plugins to it.

A `[[plugins]]` block is only for a plugin you built or unpacked yourself:

```toml
[[plugins]]
id      = "plugin.custom"
binary  = "plugins/hc-custom/bin/hc-custom"
config  = "plugins/hc-custom/config/config.toml"
enabled = true
```

Each plugin's settings live in `config/plugins/<plugin_id>.toml` and are edited from the plugin's **Settings** tab. See [plugins-and-runtimes.md](plugins-and-runtimes.md).

## Settings to leave alone

- `[auth].whitelist` gives full admin, with no sign-in, to listed addresses. It is deprecated and accepts single addresses only. Use an API key instead.
- `[auth].jwt_secret` inline is deprecated; the managed `data/jwt_secret` file is better.
- `[web_admin]` stays off. The web app serves the UI.

## Other files under config/

- `config/modes.toml`: modes, created on first start (`mode_night`, `mode_day`). Edit from **Settings › Modes**.
- `config/glue.toml`: virtual devices created at startup. Edit from **Settings › Helpers**.
- `config/calendars/`: `.ics` files for calendar rules. Manage from **Settings › Data & backups › Calendars**.
- `config/profiles/`: ecosystem profiles for Tasmota, Shelly and similar devices.
