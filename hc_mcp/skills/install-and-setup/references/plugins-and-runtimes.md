# Plugins and plugin runtimes

A plugin connects homeCore to one kind of device or service (Hue, Lutron, Z-Wave, the weather, cameras). Each is a separate program. Plugins written in Rust run inside core as child processes. Plugins written in Python run in a **plugin runtime**, a container you start yourself.

Public docs:
- https://homecore.io/docs/plugins/overview
- https://homecore.io/docs/plugins/runtimes
- Each plugin has its own page, for example https://homecore.io/docs/plugins/hue

## Who can do what

| Task | Needs |
|---|---|
| See plugins and their status | Admin, or a role with `plugins:read` (Observer, Device operator, Rule editor) |
| Install, update, configure, restart, uninstall, add runtimes | `plugins:write`, which only Admin has |

If you are the in-app Assistant: you can report a plugin's status and run its actions where the person's role allows, but installing, updating, uninstalling and adding runtimes are for an admin. Tell the person the screen below and that an admin needs to do it.

## Add a plugin from the Catalog

1. Open **Settings › Plugins** and press **Catalog**. The page reads the signed registry ("From the homeCore registry · signed releases").
2. Pick a category (Lighting, Climate, Hubs, Media, Security, Weather and so on). **Show installed** also lists what is already there.
3. Choose the plugin. The right side shows its versions, size and what it needs.
4. Press **Install <name>**. homeCore downloads it, checks its signature, unpacks it and starts it, then opens the plugin's page.
5. Open the **Settings** tab and fill in what it asks for (hub address, account, API key). Press **Save**. If the page then says it reads its settings when it starts, press **Restart <name>**.

**Check it works:** the **Overview** tab shows it running with a version, devices and "Last heard". Its devices appear under **Settings › Devices**. Banners at the top of its page say what it still needs (missing credentials, a hub that does not answer, nothing found yet) and how to fix it.

If a version needs a newer homeCore, the Catalog says so ("needs homeCore X or later") and disables the button. Upgrade core first.

Discovery-based plugins (Hue, Sonos, WLED, Roku, Ecowitt) find nothing on the Docker bridge network. See [docker.md](docker.md#pick-a-compose-file).

## A plugin's page

**Settings › Plugins**, then the plugin's row.

- Tabs: **Overview**, **Settings**, **Log**, **Devices**.
- **Restart**, **Start**, **Stop**: run control.
- **Turn off** / **Turn on**: keep it installed but not running.
- **Update**: shown when the registry has a newer version.
- **Actions**: plugin-specific commands, such as pairing a Hue bridge, including a Z-Wave device or rescanning.
- Log level: pick a level for this plugin; from core 0.1.81 it is kept in the plugin's settings.
- **Delete all its devices…**: clears its devices; the plugin registers live ones again on its next sync.
- **Uninstall…**: stops it and deletes its program. It can be added again from the Catalog.

The **Settings** tab has a **Form** and the raw `<plugin_id>.toml` file (**Edit the file…**, **Save the file**). Passwords are hidden in the file view. Settings are stored in `config/plugins/<plugin_id>.toml`; core restarts just that plugin when the file changes.

## Updates

The Plugins list marks rows with **Update**. With more than one waiting, **Update all (n)** updates them together. Updating keeps each plugin's settings. Pulling a new core image or tarball does not update plugins; they live in the data folder.

## Offline install

On a host that cannot reach the registry, download the plugin's signed artifact (`plugin.<name>-X.Y.Z-linux-x86_64.tar.zst`) from its GitHub release and hand it to core. Core treats it like a Catalog install:

```sh
curl -s -X POST http://localhost:8080/api/v1/plugins/install \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path": "/abs/path/to/plugin.<name>-X.Y.Z-linux-x86_64.tar.zst"}'
```

## Plugin runtimes (Python plugins)

The Catalog marks these plugins "Runs in a Python runtime". With no runtime yet, it shows **Needs a Python runtime** and links to **Add a runtime**. The Assistant (hc-mcp) is one.

A runtime holds any number of plugins, each in its own process and Python environment. homeCore never starts or stops the container.

### Before you start: the broker

The runtime reaches homeCore's broker over the network. If **Plugin runtimes** shows **Runtimes can't reach the broker yet**, choose **Open the broker to the network** (admin; homeCore restarts and every connection then needs a login, which homeCore makes for you). On Docker, `compose.yml` must publish 1883; older copies need `- "1883:1883"` added under `homecore` `ports`.

### Add a runtime

1. Open the app by the host's network address (`http://<homecore-host>:3001`), not `localhost`. The runtime will use that address.
2. **Settings › Plugins › Plugin runtimes › Add runtime**.
   - **Name**: anything.
   - **Language**: Python 3.12.
   - **How it reaches homeCore**: filled from the address in the browser. Change it if the runtime reaches homeCore another way.
   - **Most plugins it may hold**: blank for no limit; a few suit a Raspberry Pi.
3. Press **Add and make key**. The **Connection key** is shown once. Copy it. **Show details** lists what is inside (homeCore address, broker, runtime id and password) for a hand setup.
4. On `<runtime-host>`, from the docker repository:

   ```sh
   mkdir runtime-python-data
   docker compose -f compose.runtime-python.yml up -d
   ```

5. Open `http://<runtime-host>:8790`, paste the key, choose **Connect**. The runtime tests homeCore and the broker before saving the key and names whichever it could not reach. Alternatively set `HC_RUNTIME_KEY` in the compose file before starting it.

**Check it works:** the runtime's card on **Plugin runtimes** changes from "Waiting for it to connect" to **Connected**. **Open its page** links to the runtime's own page, which shows its plugins and logs.

### Install into it

Install the Python plugin from the Catalog as usual. With one suitable runtime it goes there; with several the Catalog asks "More than one runtime can run it. Which one?" and the button reads **Run it on <runtime>**. The runtime installs and starts it within seconds (homeCore 0.1.114 and runtime 0.2.2; an older pair waits for the next check-in, up to half a minute), and the Catalog opens the plugin once it is running. Its settings are edited in homeCore like any plugin's.

### Runtime container settings

| Variable | Default | Purpose |
|---|---|---|
| `HC_RUNTIME_KEY` | unset | The connection key, instead of pasting it on the page |
| `HC_RUNTIME_PAGE_PORT` | `8790` | The runtime's page; `0` turns it off |
| `HC_RUNTIME_PAGE_URL` | unset | The page's address, for the link in homeCore when the runtime is on another machine or port |
| `HC_RUNTIME_BROKER_HOST` | unset | The broker's address when it differs from the host in the key |
| `HC_RUNTIME_POLL_SECS` | `30` | How often it checks in. With homeCore 0.1.114 and runtime 0.2.2 it also checks in at once when a plugin is installed, updated or uninstalled there |
| `HC_RUNTIME_NETWORK_MODE` | unset | Shown in homeCore's list (`bridge`, `host`) |

The volume at `/var/lib/hc-runtime` holds the key and installed plugins. Losing it only means pasting the key again; homeCore sends the plugins back.

### Manage a runtime

- **Reset login**: makes a new key and stops the old one. The runtime stops its plugins until the new key is pasted on its page.
- **Change limit**: the most plugins it may hold.
- **Remove**: uninstalls its plugins with their devices and settings, and ends its key. Stop the container yourself.
- Moving a runtime to another homeCore: remove it from the first one, then paste the new key.
- If the Catalog says a runtime "is version X, and homeCore expects Y or later", pull the newer runtime image and restart its container. The runtime image's version follows core's.

## The Assistant

The Assistant (`plugin.mcp`, from hc-mcp) adds an **Ask** button to the app, for anyone signed in. It needs core 0.1.110 or later and app 0.1.74 or later.

1. Add a Python runtime (above).
2. Install **Assistant** from the Catalog.
3. An admin opens **Settings › Plugins › Assistant** and adds a Claude API key and picks the model. Questions, and the house details needed to answer them, go to Anthropic.

It never does more than the person asking may do. Changes wait on a confirmation card unless an admin turns that off. Devices marked Security (locks, doors) need a separate switch, off by default. homeCore gives the plugin its own API key; nothing else needs pasting.

Docs: https://homecore.io/docs/tools/hc-mcp
