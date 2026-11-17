# Binary release and system service

The release tarball is core only: the static `homecore` binary, the example config, ecosystem profiles and service templates. It has no web app, so a binary install also runs the app (`hc-web-svelte`), usually as one container pointed at core.

Public docs:
- https://homecore.io/docs/getting-started/binary-releases
- https://homecore.io/docs/getting-started/installation
- https://homecore.io/docs/administration/systemd-deployment

## Requirements

- Linux on x86_64. The binary is statically linked against musl, so it needs no glibc or OpenSSL. No arm64, macOS or Windows builds are published; those need a source build.
- Ports 8080 (API) and 1883 (broker) free on the host.

## Install core

Releases are on https://github.com/homeCore-io/homeCore/releases. Core tags look like `vX.Y.Z`; tags like `hc-hue-vX.Y.Z` are plugins, and GitHub's "Latest" label is often a plugin. Pick the newest `v*` tag.

```sh
mkdir -p ~/homecore-install && cd ~/homecore-install
V=vX.Y.Z    # newest core tag
curl -fsSLO https://github.com/homeCore-io/homeCore/releases/download/$V/homecore-core-$V-linux-x86_64.tar.gz
curl -fsSLO https://github.com/homeCore-io/homeCore/releases/download/$V/homecore-core-$V-linux-x86_64.tar.gz.sha256
sha256sum -c homecore-core-$V-linux-x86_64.tar.gz.sha256     # must say OK
tar -xzf homecore-core-$V-linux-x86_64.tar.gz                 # creates ./homecore/

cd homecore
cp config/homecore.toml.example config/homecore.toml
$EDITOR config/homecore.toml          # at least [location]
./bin/homecore --home "$PWD" --config config/homecore.toml
```

Always start from the example file. With no config file core falls back to built-in defaults, which bind the broker to `0.0.0.0` with no logins, and core refuses to start that way.

The first start prints the admin password in a log banner and writes it to `homecore/INITIAL_ADMIN_PASSWORD`.

**Check it works:** `curl http://localhost:8080/api/v1/health` returns `{"status":"ok","version":"..."}`.

## Where things go

homeCore uses one base directory for everything (the "home"). It is chosen in this order: `--home <path>`, then the `HOMECORE_HOME` variable, then the current working directory. The config file is `--config <path>`, then `HOMECORE_CONFIG`, then `config/homecore.toml` under the home. A relative `--config` is resolved against the home.

```
homecore/
  bin/homecore
  INITIAL_ADMIN_PASSWORD   first start only; delete after signing in
  config/homecore.toml     your config
  config/plugins/          plugin settings and managed.toml
  config/profiles/         ecosystem profiles
  plugins/                 installed plugins
  rules/                   automation rules
  data/                    state.redb, history.db, jwt_secret
  backups/                 scheduled backups
  logs/                    log files
```

Core creates the missing folders on start. Pass `--home` explicitly in scripts and services so the working directory never matters.

## Run the web app beside it

The simplest way is the app's container, with `HC_CORE_URL` pointing at core:

```sh
docker run -d --name hc-web-svelte --restart unless-stopped \
  -p 3001:3000 \
  -e HC_CORE_URL=http://<homecore-host>:8080 \
  -v hc-web-svelte-data:/data \
  ghcr.io/homecore-io/hc-web-svelte:latest
```

Core's `[server] host` is `0.0.0.0` by default, so the container can reach it on the host's address. Keep `/data` on a volume; it holds the app's pages, displays and each person's Home.

Without Docker, the app runs from source with Node (`npm install`, set `HC_CORE_URL`, `npm run build && npm start`, configured with `PORT`, `HOST`, `HC_CORE_URL` and `HC_DATA_DIR`). See https://homecore.io/docs/web-ui/overview.

**Check it works:** `curl http://<homecore-host>:3001/api/v1/health` gives the same answer as core, and the sign-in page loads at `http://<homecore-host>:3001`.

## Run core as a systemd service

The tarball ships `scripts/service-templates/homecore.service` with three placeholders: `@@USER@@`, `@@GROUP@@` and `@@INSTALL_DIR@@` (the absolute path of the `homecore/` folder). It runs `bin/homecore --home @@INSTALL_DIR@@ --config config/homecore.toml` with `Restart=on-failure`.

```sh
sudo useradd --system --home-dir /opt/homecore --shell /usr/sbin/nologin homecore   # optional service user
sudo mv homecore /opt/homecore && sudo chown -R homecore:homecore /opt/homecore
sudo sed -e 's|@@USER@@|homecore|g; s|@@GROUP@@|homecore|g; s|@@INSTALL_DIR@@|/opt/homecore|g' \
  /opt/homecore/scripts/service-templates/homecore.service \
  | sudo tee /etc/systemd/system/homecore.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now homecore
```

**Check it works:**

```sh
systemctl status homecore
journalctl -u homecore -f                       # look for the admin banner on first start
curl http://localhost:8080/api/v1/health
```

Restarting from the app (**Restart homeCore…**) or `POST /api/v1/system/restart` exits with code 75 so systemd starts core again. On cores before v0.1.97 it exited with 0 and stayed stopped; use `sudo systemctl restart homecore` there.

There is no reload: homeCore has no SIGHUP handler. Use `systemctl restart homecore`.

For a fuller setup with a separate Mosquitto broker, follow https://homecore.io/docs/administration/systemd-deployment.

### macOS

The tarball also carries `com.homecore.homecore.plist`, a launchd template, but no macOS binary is published. A source checkout has `scripts/install-service.sh`, which fills in the systemd or launchd template for you (`--install-dir`, `--user`, `--user-agent`, `--status`, `--uninstall`).

## Plugins on a binary install

Install plugins from the Catalog in the app, the same as on Docker. Core downloads the signed artifact, unpacks it under `plugins/` and records it in `config/plugins/managed.toml`. You do not edit `homecore.toml` for this.

Hand-unpacked plugin tarballs (`hc-<name>-vX.Y.Z-linux-x86_64.tar.gz`) are for a build you want to supervise from your own path. Those need a `[[plugins]]` block; see [configuration.md](configuration.md#plugins-blocks). On a host with no internet access, see [plugins-and-runtimes.md](plugins-and-runtimes.md#offline-install).

## Upgrade

See [maintenance.md](maintenance.md#upgrade).
