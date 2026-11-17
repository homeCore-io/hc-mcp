# Docker install

The Docker stack is two containers from the `homeCore-io/docker` repository:

| Service | Image | Port on the host | What it does |
|---|---|---|---|
| `homecore` | `ghcr.io/homecore-io/hc-core` | 8080 (API), 1883 (broker) | Core: API and embedded MQTT broker. Plugins run inside it as child processes. |
| `app` | `ghcr.io/homecore-io/hc-web-svelte` | 3001 | The web app. Passes `/api/v1` to core at `HC_CORE_URL`. |

Plugins are not containers. They are installed from the Catalog in the app. Adding hardware never means editing a compose file.

Public docs: https://homecore.io/docs/getting-started/docker

## Pick a compose file

| File | Networking | Use it when |
|---|---|---|
| `compose.yml` | bridge | Start here. Plugins that make ordinary outbound connections (YoLink, Lutron, Caséta, ISY, Z-Wave and cloud services) work on it. |
| `compose.host.yml` | host | Hue, Sonos, WLED, Roku or Ecowitt are in the house, or discovery found nothing. Linux only. |
| `compose-dev.yml` | bridge | You want the `:dev` images, built from the develop branch on request. |
| `compose.runtime-python.yml` | bridge | An add-on: a runtime for Python plugins, on this machine or another. See [plugins-and-runtimes.md](plugins-and-runtimes.md). |

Why host networking: Hue, Sonos, WLED and Roku find devices with mDNS and SSDP (multicast), and Ecowitt with a UDP broadcast. A bridge network carries neither, so those plugins install and run and then find nothing. Sonos also needs speakers to call back to an address they can reach. Docker Desktop on macOS and Windows runs containers in a VM, so host networking there does not reach the LAN either.

Ecowitt can stay on the bridge: set `gateway_ip` in its settings and it polls the gateway over ordinary HTTP.

## Install

```sh
git clone https://github.com/homeCore-io/docker.git homecore-docker
cd homecore-docker
mkdir homecore-data                     # as your own user
docker compose up -d                    # or -f compose.host.yml
cat homecore-data/INITIAL_ADMIN_PASSWORD
```

Then open `http://<homecore-host>:3001`, sign in as `admin`, change the password on **Me › Password**, and delete `INITIAL_ADMIN_PASSWORD`.

Deploying through a stack manager (Portainer, Dockhand and similar) works too. Paste the whole compose file: the `networks:` block at the bottom is what lets the app find `homecore` by name.

**Check it works:**

```sh
docker compose ps                                  # both services running
curl http://<homecore-host>:8080/api/v1/health     # core directly
curl http://<homecore-host>:3001/api/v1/health     # through the app
curl http://<homecore-host>:3001/ui/health         # the app's own server: {"ok":true}
```

## What lives where

Core keeps everything in one bind-mounted folder, `homecore-data/`, mounted at `/homecore` inside the container:

```
homecore-data/
  INITIAL_ADMIN_PASSWORD   first boot only; delete after signing in
  config/homecore.toml     seeded on first boot from the image's default; yours to edit
  config/modes.toml        modes
  config/plugins/          each plugin's settings, <plugin_id>.toml, and managed.toml
  data/state.redb          devices, users, keys, scenes, rooms
  data/history.db          time-series history
  data/jwt_secret          sign-in signing secret (keep private)
  plugins/<id>/<version>/  installed plugin binaries
  rules/                   automation rules, reloaded on change
  backups/                 scheduled backups (daily by default)
  logs/                    homecore.YYYY-MM-DD log files
```

The app keeps its own data (pages, displays, each person's Home, the house's look, pictures) in the `app-data` named volume at `/data`. homeCore's backup does not include it; **Settings › Data & backups › save them too** saves it.

There is no config bind-mount. The image writes `config/homecore.toml` on first boot and never overwrites it afterwards. To change settings, use **Settings › Configuration** in the app, or edit the file and run `docker compose restart homecore`.

### File ownership

`mkdir homecore-data` as yourself is the whole setup. The entrypoint starts as root, reads the folder's owner and drops to that user. If Docker created the folder (owned by root), the entrypoint gives it to `HOMECORE_UID:HOMECORE_GID`, default `1000:1000`.

## Ports and environment

| Variable | Default | Meaning on `compose.yml` | Meaning on `compose.host.yml` |
|---|---|---|---|
| `HC_WEB_PORT` | 3001 | Host side of the app's mapping | Port the app binds on the host |
| `HC_API_PORT` | 8080 | Host side of core's mapping | Where the app looks for core; must match `[server] port` |
| `HC_BROKER_PORT` | 1883 | Host side of the broker mapping | (no mappings in host mode) |

```sh
HC_WEB_PORT=8800 HC_API_PORT=8801 docker compose up -d
```

Other settings on the core container:

- `RUST_LOG`: log filter, `info` by default. Overrides `[logging]` levels.
- `HC_BROKER_BIND`: on a fresh `homecore-data` only, written into `[broker] host` when the config is seeded.
- `HC_ALLOW_ANONYMOUS_REMOTE_BROKER=1`: lets core start with a network-facing broker and no logins. Avoid it.

On the app container:

- `HC_CORE_URL`: where the app's server reaches core. `http://homecore:8080` on the bridge stack, `http://127.0.0.1:8080` in host mode, or `http://<homecore-host>:8080` when the app runs elsewhere.
- `HC_GO2RTC_URL`: optional, for live camera video through go2rtc. Without it, cameras show snapshots.

## The broker port

`compose.yml` publishes 1883, but nothing answers there at first: the default config binds the broker to `127.0.0.1` inside the container, where core's own plugins reach it. Plugin runtimes and LAN devices (Tasmota, Shelly, ESPHome) need it on the network. Use **Settings › Plugins › Plugin runtimes › Open the broker to the network**, which binds `0.0.0.0`, adds logins and restarts core. Older copies of `compose.yml` lack the 1883 mapping; add `- "1883:1883"` under the `homecore` service's `ports`.

## Image tags

| Tag | Meaning |
|---|---|
| `:latest` | Newest release. What the compose files use. |
| `:0.1.110` and so on | One release, never changes. Image tags drop the `v`. |
| `:dev`, `:dev-<sha7>` | Develop builds, made on request. |

Core, the app and the runtime image are versioned separately and their numbers do not line up. The Python runtime image's version follows core's. To pin a stack, set each image's tag explicitly. The [release notes](https://homecore.io/docs/release-notes) say which app version shipped with each core.

## Upgrade, back up, check

- Upgrade: see [maintenance.md](maintenance.md#upgrade).
- Back up: see [maintenance.md](maintenance.md#back-up).
- Container logs: `docker compose logs -f homecore` and `docker compose logs -f app`.

## Retired setups

If an old compose file has an `hc-web` service (the Flutter UI on port 3000), a `homecore-appliance` image, per-plugin containers, or a bind-mount of `homecore.toml`, those are retired. Remove them and use the current `compose.yml`. The app is on 3001.
