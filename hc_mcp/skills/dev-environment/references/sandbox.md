# Sandbox

A sandbox is a homeCore you can break. It has its own home directory, its
own config, loopback-only ports that do not collide with any other core on
the machine, and only stand-in devices. Everything you test runs here.

## Rules

- Never test against a real house. No commands to real devices.
- No discovery from a sandbox. Hue, Sonos, WLED and Roku discovery would
  find the real devices on your LAN.
- Reading a real device's info (a GET of its state or config) is allowed
  only to copy its shapes into a stand-in or a test, with secrets scrubbed.
- Bind the server and the broker to `127.0.0.1`.
- Leave `[auth].whitelist` empty. A whitelisted address gets admin with no
  token.
- Do not set `HC_ALLOW_ANONYMOUS_REMOTE_BROKER`.
- Do not copy a real plugin config (`config.dev.toml`, `config.toml`) into
  a sandbox. They hold real addresses and credentials.

## Create one

Pick free ports. These examples use 18080 (API), 11883 (MQTT) and 11884
(MQTT v5). If another core is already running, change them.

```bash
SBX=$HOME/hc-sandbox
mkdir -p "$SBX/config"
cat > "$SBX/config/homecore.toml" <<'EOF'
[server]
host = "127.0.0.1"
port = 18080

[broker]
host = "127.0.0.1"
port = 11883
v5_port = 11884
EOF
<workspace>/core/target/debug/homecore --home "$SBX" --config "$SBX/config/homecore.toml"
```

Relative paths in the config (plugin binaries, plugin configs, storage)
resolve against `--home`. The full config reference is
[Configuration](https://homecore.io/docs/getting-started/configuration).

First start creates `data/` (redb state, SQLite history, audit log, JWT
secret), `logs/`, `rules/`, `backups/`, and `INITIAL_ADMIN_PASSWORD` with
the admin password on a `Password:` line. The password is also in the
startup log banner.

### Check it works

```bash
curl -s http://127.0.0.1:18080/api/v1/health
PASS=$(sed -n 's/^Password: //p' "$SBX/INITIAL_ADMIN_PASSWORD")
TOKEN=$(curl -s -X POST http://127.0.0.1:18080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PASS\"}" | jq -r .token)
echo "$TOKEN" | cut -c1-20
```

## Add a stand-in device: the template plugin

`hc-plugin-template` simulates a light and needs no hardware. Build it,
give it a config that points at the sandbox broker, and declare it.

```bash
cd <workspace>/core && cargo build -p hc-plugin-template
mkdir -p "$SBX/plugins/hc-plugin-template/config"
sed 's/broker_port = 1883/broker_port = 11883/' \
  plugins/hc-plugin-template/config/config.toml.example \
  > "$SBX/plugins/hc-plugin-template/config/config.toml"

cat >> "$SBX/config/homecore.toml" <<EOF

[[plugins]]
id      = "plugin.template"
binary  = "$(pwd)/target/debug/hc-plugin-template"
config  = "plugins/hc-plugin-template/config/config.toml"
enabled = true
EOF
```

Restart core. Core spawns plugins only after its internal MQTT client is
subscribed, then supervises them with restart backoff.

### Check it works

```bash
curl -s http://127.0.0.1:18080/api/v1/devices -H "Authorization: Bearer $TOKEN" | jq -r '.[].device_id'
# mode_day, mode_night, template_light_1
curl -s http://127.0.0.1:18080/api/v1/plugins -H "Authorization: Bearer $TOKEN" | jq -r '.[].status'
# active
```

On first start core copies each plugin's config into
`$SBX/config/plugins/<plugin_id>.toml` and hands that path to the plugin
from then on. Edit that copy, not the original.

## Other stand-ins

| Need | Use |
|---|---|
| Switches, timers, modes, no plugin at all | Core's own glue devices. See [Virtual Devices](https://homecore.io/docs/devices/virtual-devices). |
| A plugin of your own, in any language | Point its config at the sandbox broker port, declare it with `[[plugins]]` or add it through a runtime. See [Developing Plugins](https://homecore.io/docs/plugins/developing-plugins). |
| A Reolink NVR or camera | `core/plugins/hc-reolink/standin/` (`node standin.mjs`, listens on `127.0.0.1:18996`). Its README has the plugin config. |
| Capability actions end to end | `hc-captest` in `core/plugins/hc-captest`. It reads `HC_BROKER_HOST`, `HC_BROKER_PORT` and `HC_BROKER_PASSWORD` from the environment. |
| A device a stand-in does not exist for yet | Write one: a small local server that answers the device's API in its real shapes (copied once, secrets scrubbed). Keep it beside the plugin. |

A stand-in plugin config must name `127.0.0.1` and the stand-in's port. If
a config contains a real hostname or LAN address, it is not a sandbox
config.

## Test the release layout

A sandbox can also install a built plugin package the way a real install
does, which proves the packaging:

```bash
curl -s -X POST http://127.0.0.1:18080/api/v1/plugins/install \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"path": "/path/to/hc-<name>.tar.zst"}'
```

## The workspace sandbox and `just`

The workspace `Justfile` has recipes for a sandbox at
`<workspace>/sandbox/`. They pass `--home sandbox --config
sandbox/homecore.toml`, so the config file sits at the top of that
directory (not under `config/`):

```bash
mkdir -p sandbox
cp "$SBX/config/homecore.toml" sandbox/homecore.toml   # or write a new one
just sandbox          # build homecore incrementally, then run the sandbox
just sandbox-run      # run without building
just sandbox-build    # build the workspace, run sandbox/reinstall-plugins.sh, then run
```

`sandbox-build` calls `sandbox/reinstall-plugins.sh`, which you write
yourself (for example, copy fresh plugin binaries into `sandbox/plugins/`).
No `just clean` recipe touches `sandbox/`.

## Run the web app against it

```bash
cd <workspace>/clients/hc-web-svelte
HC_CORE_URL=http://127.0.0.1:18080 npm run dev     # http://localhost:5180
```

For screen work, drive the app in a headless browser against the sandbox
and look at desktop and phone widths, in light and dark.

## Reset

Stop core, then:

```bash
rm -rf "$SBX/data" "$SBX/INITIAL_ADMIN_PASSWORD"
```

The next start creates a new admin password. `rules/` and
`config/plugins/` survive this; delete them too for a clean slate, or
delete the whole `$SBX` and start over.
