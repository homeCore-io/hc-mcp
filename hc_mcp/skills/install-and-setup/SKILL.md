---
name: install-and-setup
description: Guides installing and setting up homeCore, the local-first home automation server, for a new owner. Covers choosing Docker, a binary release or a system service, the first run and first admin sign-in, homecore.toml, the web app, adding plugins from the Catalog, plugin runtimes for Python plugins, people, roles and API keys, the MQTT broker, backups, upgrades, logs and system status, and what to check when something is wrong. Use it when someone asks to install homeCore, configure homeCore, add a plugin, set up a plugin runtime, add a user, make an API key, back up or restore homeCore, upgrade homeCore, or find out why homeCore or a plugin is not working. Also suits homeCore's in-app Assistant answering setup questions from someone in the house.
license: MIT OR Apache-2.0
---

# Install and set up homeCore

homeCore is two pieces that run side by side:

- **Core** (`hc-core`, the `homecore` binary): the REST and WebSocket API on port 8080 and an embedded MQTT broker on 1883. It serves no UI.
- **The web app** (`hc-web-svelte`): what people use, on port 3001. Its server passes `/api/v1` through to core, so people open the app and the app talks to core.

Plugins connect homeCore to devices. They are installed from the **Catalog** inside the app and run as child processes of core. Plugins written in Python (the Assistant is one) run in a **plugin runtime**, a container you start yourself.

Placeholders used throughout: `<homecore-host>` is the machine running core and the app, `<runtime-host>` is the machine running a plugin runtime. Public docs live at https://homecore.io/docs/ and each reference file links the pages it summarizes.

## If you are homeCore's Assistant

You are talking with someone in the house through the app's Ask panel. You can read the house and act through homeCore's API tools, limited to what that person's role allows.

- Always name the screen that does the job, for example "Settings › Plugins › Catalog", so the person can do it or check it themselves.
- Installing or removing plugins, adding runtimes, changing people, roles, passwords or API keys, opening the broker, editing `homecore.toml`, restoring a backup and restarting homeCore are admin tasks. Say so plainly, tell the person which screen an admin would use, and do not try them silently or work around a refusal.
- Installing homeCore itself, upgrading it and starting containers happen on the host machine, outside the app. Explain the steps; you cannot run them.
- Never ask for, repeat or store passwords, connection keys or API keys in the chat.

## Step 1: Choose how to install

| Method | Choose it when | Read |
|---|---|---|
| **Docker stack** (recommended) | Almost everyone. One `compose.yml` runs core and the app together, and upgrades are two commands. | [references/docker.md](references/docker.md) |
| **Binary release** | No Docker, or you want core as a plain process. Linux x86_64 only. You still run the app separately (its container is simplest). | [references/binaries-and-service.md](references/binaries-and-service.md) |
| **Binary as a system service** | A binary install that starts at boot under systemd (or launchd on macOS). | [references/binaries-and-service.md](references/binaries-and-service.md) |
| **Build from source** | Plugin authors and core developers. Out of scope here; see the `dev-environment` skill. | https://homecore.io/docs/getting-started/installation |

Docker networking decides whether device discovery works. Hue, Sonos, WLED, Roku and Ecowitt discover devices by multicast or broadcast, which a Docker bridge network does not carry. If any of those are in the house, use `compose.host.yml` (Linux only). Everything else works on the default `compose.yml`.

Questions to settle before starting:

1. Which machine runs homeCore, and will it run Docker?
2. Which device brands are in the house? (This picks the compose file and the plugins.)
3. Will anyone use the Assistant or another Python plugin? (Then plan a plugin runtime.)

## Step 2: Install and start core and the app

Follow the reference for the chosen method. The short Docker version:

```sh
git clone https://github.com/homeCore-io/docker.git homecore-docker
cd homecore-docker
mkdir homecore-data            # as your own user, not root
docker compose up -d           # or: docker compose -f compose.host.yml up -d
```

**Check it works:**

```sh
docker compose ps                                   # both services running
curl http://<homecore-host>:8080/api/v1/health      # core: {"status":"ok","version":"..."}
curl http://<homecore-host>:3001/api/v1/health      # the same answer, through the app
```

If core answers and the app does not, the app cannot reach core. See [references/troubleshooting.md](references/troubleshooting.md).

## Step 3: First sign-in as admin

On its first start, with no users yet, core creates an `admin` account with a random password. It prints the password in a log banner and writes it to `INITIAL_ADMIN_PASSWORD` in homeCore's home directory (`homecore-data/` under Docker).

1. Read the password: `cat homecore-data/INITIAL_ADMIN_PASSWORD`.
2. Open `http://<homecore-host>:3001` and sign in as `admin`.
3. Change the password on **Me › Password**.
4. Delete the `INITIAL_ADMIN_PASSWORD` file.

**Check it works:** you see Home, and the gear opens Settings with both the House and System groups. Signing in again with the new password works.

If the password file is lost before anyone signs in, see "Lost the first admin password" in [references/troubleshooting.md](references/troubleshooting.md).

## Step 4: Set the basics in homecore.toml

Open **Settings › Configuration**. The **Form** tab edits `homecore.toml` section by section; the **homecore.toml** tab shows the raw file (**Edit the file…**, then **Save homecore.toml**). Most changes take effect after **Restart homeCore…**.

Set at least:

- `[location]` latitude, longitude and time zone, so sunrise and sunset rules are right.
- `temperature_unit` under `[location]` if the house uses °F.
- `[backup]` if the daily schedule (every 24 hours, keep 7) does not suit.

**Check it works:** **Settings › System** shows the version, uptime and time zone you expect.

Details and every section: [references/configuration.md](references/configuration.md).

## Step 5: Add plugins from the Catalog

1. **Settings › Plugins**, then **Catalog**.
2. Pick a category, choose a plugin, and press **Install <name>**.
3. The plugin opens on its page. Fill in its **Settings** tab (hub address, account, and so on) and save.

**Check it works:** on **Settings › Plugins** the plugin shows as running with a device count above zero. Banners on its page explain anything it still needs. Its devices appear under **Settings › Devices**.

Python plugins first need a runtime (Step 6). Details: [references/plugins-and-runtimes.md](references/plugins-and-runtimes.md).

## Step 6 (optional): Add a plugin runtime for Python plugins

Needed for the Assistant and any other plugin the Catalog marks "Runs in a Python runtime".

1. **Settings › Plugins › Plugin runtimes › Add runtime**. Check **How it reaches homeCore** holds an address the runtime's machine can reach (open the app by its network address first, not `localhost`). Press **Add and make key** and copy the connection key, which is shown once.
2. If the page says **Runtimes can't reach the broker yet**, choose **Open the broker to the network** (homeCore restarts).
3. On `<runtime-host>`: `mkdir runtime-python-data && docker compose -f compose.runtime-python.yml up -d`.
4. Open `http://<runtime-host>:8790`, paste the key and choose **Connect**.

**Check it works:** the runtime's card on **Plugin runtimes** says **Connected**. Then install the Python plugin from the Catalog as in Step 5.

Details: [references/plugins-and-runtimes.md](references/plugins-and-runtimes.md).

## Step 7: Add the household

1. **Settings › People & access › + Add a person**.
2. Pick what they may do (Household member suits family; keep Admin to one or two people), set **Name they sign in with** and **First password** (8 characters or more), and press **Add as …**.

**Check it works:** they appear in the list with the right role, and can sign in from their own phone.

Details, every role and wall tablets: [references/users-and-access.md](references/users-and-access.md).

## Step 8: Confirm backups

Open **Settings › Data & backups** and press **Back up now**. Then use **save them too** to save the app's own data (pages, displays, everyone's Home), which homeCore's backup does not hold.

**Check it works:** the card shows the time of the last backup and lists the backups kept on the house. Copy one off the machine.

Details: [references/maintenance.md](references/maintenance.md).

## Task index

Each task is a few lines here; the reference has the full procedure.

**Add a plugin.** Admin. **Settings › Plugins › Catalog**, choose it, **Install <name>**, then fill in its **Settings** tab. Updates show on the Plugins list as **Update** or **Update all (n)**. Read [references/plugins-and-runtimes.md](references/plugins-and-runtimes.md) for settings, actions, uninstalling and offline installs.

**Add a plugin runtime.** Needs the plugins permission. **Settings › Plugins › Plugin runtimes › Add runtime**, copy the key, start `compose.runtime-python.yml`, paste the key on port 8790. Lost key: **Reset login**. Read [references/plugins-and-runtimes.md](references/plugins-and-runtimes.md).

**Add a user.** Admin. **Settings › People & access › + Add a person**. Change a role or reset a password from the person's page. Read [references/users-and-access.md](references/users-and-access.md).

**Make an API key.** **Settings › People & access › API keys** (or **Me › API keys** for your own). Fill **What it's for** and **What it may do**, press **Make the key**, copy it once. Read [references/users-and-access.md](references/users-and-access.md).

**Back up or restore.** Admin. **Settings › Data & backups**: **Back up now**, **save them too**, and **Restore** with **Choose a backup file…** or **Put back…** on a kept backup. Read [references/maintenance.md](references/maintenance.md).

**Upgrade.** Docker: `docker compose pull && docker compose up -d`. Binary: extract the new core tarball over the install and restart. Plugins update from **Settings › Plugins**. **Settings › System** says when a new homeCore or app is out. Read [references/maintenance.md](references/maintenance.md).

**Open the broker to LAN devices or runtimes.** Admin. **Plugin runtimes › Open the broker to the network**, or edit `[broker]` by hand. Read [references/configuration.md](references/configuration.md).

**Read logs and status.** **Settings › Logs** (live, core and plugins), a plugin's **Log** tab, **Settings › System** for version, health and log level. Read [references/maintenance.md](references/maintenance.md).

**Something is wrong.** Start with [references/troubleshooting.md](references/troubleshooting.md).

## Reference files

| File | Read it when |
|---|---|
| [references/docker.md](references/docker.md) | Installing or running the Docker stack: compose files, ports, the data folder, host networking. |
| [references/binaries-and-service.md](references/binaries-and-service.md) | Installing the release tarball, running it under systemd or launchd, running the app beside it. |
| [references/configuration.md](references/configuration.md) | Editing `homecore.toml`, paths and flags (`--home`, `--config`), the broker, the registry. |
| [references/plugins-and-runtimes.md](references/plugins-and-runtimes.md) | Installing, configuring, updating or removing plugins; setting up a Python runtime; the Assistant. |
| [references/users-and-access.md](references/users-and-access.md) | People, roles, passwords, API keys, displays, sessions. |
| [references/maintenance.md](references/maintenance.md) | Backups, restore, upgrades, logs, system status, moving to a new machine. |
| [references/troubleshooting.md](references/troubleshooting.md) | Something does not start, cannot connect, finds no devices, or refuses a request. |
