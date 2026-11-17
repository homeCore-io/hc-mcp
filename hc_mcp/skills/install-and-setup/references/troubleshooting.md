# When something is wrong

Work from the outside in: is core up, can the app reach it, is the plugin running, is the device answering. Each symptom below lists what to check and the fix.

Public docs for depth: https://homecore.io/docs/getting-started/docker (health checks), https://homecore.io/docs/administration/broker, https://homecore.io/docs/administration/logging.

If you are the in-app Assistant: you can read status, plugin notices, recent events and device state to narrow things down. Report what you find and name the screen to look at. Fixes that change configuration, plugins, the broker or accounts are for an admin; say so.

## First checks

```sh
curl http://<homecore-host>:8080/api/v1/health     # core
curl http://<homecore-host>:3001/api/v1/health     # core through the app
curl http://<homecore-host>:3001/ui/health         # the app's own server
```

Then the logs: `docker compose logs --tail 100 homecore` (Docker) or `journalctl -u homecore -n 100` (systemd). In the app: **Settings › Logs**, and **Settings › Plugins** for anything not running.

## Core does not start

**Log says the broker is bound to a non-loopback address with no clients.** Core refuses to run an open broker. Either set `[broker] host = "127.0.0.1"`, or add `[[broker.clients]]` logins including `internal.core`. See [configuration.md](configuration.md#the-mqtt-broker-broker). A TOML syntax error causes this too: a file that does not parse falls back to defaults, which bind `0.0.0.0`. Check the file for a typo.

**Address already in use on 8080 or 1883.** Something else holds the port (`ss -tlnp | grep -E '8080|1883'`). Move core with `[server] port`, or with `HC_API_PORT` / `HC_BROKER_PORT` on Docker. On a Mosquitto setup, core started its own broker because `[broker] external_url` is unset.

**Docker: permission denied writing under `/homecore`.** The data folder or a subfolder is owned by root. Create `homecore-data` as your own user; if a subfolder is still root-owned, run `sudo chown -R "$(id -u):$(id -g)" homecore-data` and start again. `cp: can't create '/homecore/config/homecore.toml/config.toml'` means an old compose file bind-mounts `homecore.toml`; remove that mount.

**A Telegram channel still says `CHANGE_ME`.** Core stops at boot on that placeholder. Fill it in or remove the channel.

## The app does not load or cannot reach homeCore

**Nothing on port 3000.** The app is on 3001. Port 3000 was the retired Flutter UI.

**The app loads but every page fails, while core is healthy.** The app's server cannot reach core. Check `HC_CORE_URL` on the app container. Deployed through Portainer or another stack manager, the `networks:` block was probably dropped, so the name `homecore` does not resolve; paste the whole `compose.yml`. In host mode `HC_CORE_URL` must be `http://127.0.0.1:<core port>`.

**Signed out over and over.** A password or role change ends that person's sessions everywhere. Check **Me › Signed in**. Five failed sign-ins in a minute from one address are blocked briefly.

## Sign-in problems

**Lost the first admin password, nobody has signed in yet.** It is in `INITIAL_ADMIN_PASSWORD` under homeCore's home, and in the first-start log. If both are gone, stop core and delete `data/`; the next start creates a new admin and password. This deletes devices, users and history, so only do it on a new install.

**Forgot a password.** Another admin resets it from the person's page (**Set a new password…**). There is no email reset.

**403 Forbidden, or a Settings section is missing.** The role lacks the permission. An admin changes the role on **Settings › People & access**, or gives the API key the needed scope.

## Plugins

**The Catalog says it cannot read the registry, or installs fail with 503.** `[registry] url` or `public_key` is missing from `homecore.toml`, or the host has no internet access. Restore them from the shipped example, or use the offline install in [plugins-and-runtimes.md](plugins-and-runtimes.md#offline-install).

**Installed and running, but no devices.** Open the plugin's page and read the banners; most say exactly what is missing (credentials, hub address). Fill in its **Settings** tab and restart it. For Hue, Sonos, WLED, Roku and Ecowitt on Docker, discovery needs `compose.host.yml` (or, for Ecowitt, `gateway_ip`).

**Keeps restarting.** Core restarts a crashed plugin with backoff from 2 to 60 seconds. Read its **Log** tab, raise its log level for a while, and check its settings.

**Marked offline.** Core marks a plugin offline after 90 seconds without a heartbeat. Check that it is running, and on a network-facing broker that its login is valid.

**Settings changes do nothing.** Plugins read settings when they start. After saving, press **Restart <name>** on its page.

## Plugin runtimes

**Runtime stays "Waiting for it to connect".**
- The runtime's page (port 8790) says which it could not reach: homeCore or the broker.
- homeCore unreachable: the key holds the address from **How it reaches homeCore**. If that was `localhost`, the runtime cannot use it. **Reset login**, add again from the host's network address, paste the new key.
- Broker unreachable: **Plugin runtimes** shows **Runtimes can't reach the broker yet**; choose **Open the broker to the network**. On Docker, make sure `compose.yml` publishes 1883. Set `HC_RUNTIME_BROKER_HOST` if the broker is on a different address from homeCore.
- A runtime still added in another homeCore refuses a new key. Remove it there first.

**"Not heard from".** The container stopped or lost the network. `docker compose -f compose.runtime-python.yml ps` and `logs` on the runtime's machine.

**Catalog says the runtime is too old.** Pull the newer runtime image and restart its container; its version follows core's.

## Rules and time

**Sunrise or sunset rules fire at odd times.** `[location]` is unset or wrong, or the time zone is. Check **Settings › System** for the time zone and set `[location]`.

**Rules reference devices that no longer exist.** `GET /api/v1/automations/stale-refs` lists them.

## After a restart from the app, homeCore stays down

On systemd with cores before v0.1.97, a restart from the app exited cleanly and systemd left it stopped. Run `sudo systemctl restart homecore`, and upgrade.

## Still stuck

Collect, without passwords or keys: the version from `/api/v1/health`, the install method, the last 100 log lines around the problem, and the plugin's notices. Then see https://homecore.io/docs/ or open an issue on https://github.com/homeCore-io/homeCore/issues.
