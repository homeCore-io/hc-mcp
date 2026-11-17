# A plugin's own screens and cards

Read this when a plugin needs its own UI: a page, a device panel, a card, an
automation step form, a look's drawing, or an assistant panel. The types are
`@homecore/plugin-ui` at `sdk/ui/index.d.ts` in the homeCore repository (not
on npm; use it from a checkout). Public page:
[Plugin Screens and Cards](https://homecore.io/docs/plugins/plugin-screens).

## The rule

**Screens ship with the plugin.** The plugin carries a built `ui/` folder and
serves it over the management channel; homeCore passes the files through and
keeps none; the web app loads them into slots. The web app holds no
plugin-specific code, so never add a plugin's screen to the app: give the
plugin a slot. Screens use only the `host` they are handed, never the app's
internals.

Before writing a screen, check whether the schema already covers it. An
integer attribute with named `options` is offered and spoken by name in
every picker and automation sentence with no screen at all.

## Slots

| Slot | Where | The element is given |
|---|---|---|
| `plugin.page` | its page in Settings › Plugins, in place of the generic action list | `host` |
| `device.panel` | its devices' panel, in place of the generic controls | `host`, `deviceId` |
| `rule.step` | the automation editor's form for a step that sets its devices | `host`, `deviceIds`, `value` |
| `device.card` | its devices' card on Home, the rooms and favorites | `host`, `deviceId`, `form` |
| `dashboard.card` | a card of its own, added from "Add a card" | `host`, `form`, `config` |
| `look.drawing` | how a family of things is drawn, in a look that chooses it | `host`, `thing`, `deviceId` |
| `look.piece` | a room's header or a display's rest view | `host`, `room` or `things` |
| `look.symbol` | symbols a person can give any device | `host`, `name` |
| `app.assistant` | a helper in the app's top bar, opened as a side panel or a page (app after 0.1.73) | `host`, `mode` (`panel` or `page`) |

homeCore passes every slot and its fields to the app as written, and checks
only that `slot` is a dotted lowercase name and `element` is a valid custom
element name. The app ignores what it doesn't know, so a newer slot does no
harm on an older app.

## The folder

One ES module with everything bundled into it, plus `manifest.json`:

```json
{
  "host_api": 1,
  "entry": "index.js",
  "slots": [
    { "slot": "plugin.page", "element": "hc-demo-page" },
    { "slot": "device.panel", "element": "hc-demo-panel", "device_types": ["light"] },
    { "slot": "device.card", "element": "hc-demo-card", "device_types": ["light"],
      "forms": ["standard", "compact"] },
    { "slot": "dashboard.card", "element": "hc-demo-glance", "label": "At a glance",
      "description": "One line under it in Add a card", "forms": ["large", "standard"],
      "settings": "hc-demo-glance-settings" }
  ]
}
```

- `device_types` limits a `device.panel`, `rule.step` or `device.card` slot.
- `forms` lists a card's sizes: `compact` (one row), `standard`, `large` (two
  columns). The first is a dashboard card's size when added.
- `dashboard.card`, the `look.*` slots and `app.assistant` need a `label`.

Serve it from the plugin:

| SDK | Call |
|---|---|
| Rust | `if let Some(dir) = plugin_sdk_rs::ui::find_dir(env!("CARGO_MANIFEST_DIR")) { mgmt = mgmt.with_ui_dir(dir, env!("CARGO_PKG_VERSION")); }` |
| Python | `d = ui.find_dir(__file__)`, then `plugin.with_ui_dir(d, __version__)` |
| JavaScript | `const dir = ui.findDir(__dirname)`, then `this.withUiDir(dir, version)` |
| .NET | `if (Ui.FindDir() is { } d) client.WithUiDir(d, Version);` |

`find_dir` looks at `HC_PLUGIN_UI_DIR`, then `ui/` beside the program (how a
package installs it), then the source tree's `ui/dist`. The SDK publishes the
UI on the manifest with a hash of its files as `build` and answers
homeCore's `ui_file` requests. The browser loads
`GET /api/v1/plugins/{id}/ui/{build}/{file}` and caches each build for good;
a rebuilt UI is a new build. A stopped plugin offers no screens, and the app
falls back to its generic ones whenever a screen is missing or fails.

## The host

| Member | What it is |
|---|---|
| `devices` | its devices, live: `subscribe(f)` (called now and on every change; returns a stop function), `list()`, `get(id)`, `label(d)`, `history(id, attribute, opts)` |
| `alerts` | homeCore's alerts on its devices, live: `subscribe(f)`, `list()` |
| `command(deviceId, body)` | a command, in the two shapes: `{ on: true }` or `{ action: 'toggle' }` |
| `action(id, params)` | one of its manifest actions; the declared role applies |
| `query(id, params)` | a `read_only` action, for anyone who can see devices |
| `stream(action, params, onEvent)` | a streaming action, followed live; returns `{ requestId, cancel(), done }` (app after 0.1.73) |
| `respond(requestId, response)` | answers an `awaiting_user` stage (app after 0.1.73) |
| `upload(action, file, params)` | sends a file (up to 32 MiB) to an action; Rust plugins only |
| `fileUrl(path)` | the address of a picture the plugin keeps (Rust `with_files_dir`) |
| `config` | its settings file (admins): `get()`, `patch(section, values)`, `restartPlugin()` |
| `store` | JSON documents the app keeps for its screens, up to 2 MiB each: `get`, `put`, `remove` |
| `fetch(path)` | homeCore's API under `/api/v1`, as the person using it |
| `units` | `show(value, schemaUnit)`, `toCore(value, unit)`, `subscribe(f)` |
| `ui` | the app's `confirm(question)`, `openDevice(id)`, `navigate(href)` |
| `me` | `name`, `role`, `isAdmin`, `can(scope)`; decide what to offer with `can`, never the role |
| `user` | `username` and `role` (app after 0.1.73) |
| `theme` | `sheet` (the app's parts as a stylesheet) and `dark()` |
| `rive` | `play(canvas, options)` and `motion()` |
| `api`, `pluginId`, `appVersion` | the interface version (1), the plugin's id, the app's version |

Members added after the first release (`fetch`, `upload`, `store`, `units`,
`fileUrl`, `alerts`, `rive`, `stream`, `respond`, `user`) may be absent on an
older app. Check before use (`typeof host.stream === 'function'`) and fall
back.

A screen runs inside the app as the person using it. Everything on `host` is
still scoped to the plugin's own devices and actions.

## Contracts per slot

- **`rule.step`**: given `deviceIds` and `value` (the first device's state
  in the step). Answer with a `change` event, `detail: { action }`, holding
  the whole step: a `SetDeviceState`, or a `Parallel` of them. The editor
  takes it only if every target is the plugin's own device. The element's
  class may have statics `accepts(value)` (else the generic form shows) and
  `describe(host, deviceIds, value)`, the step in words with `{devices}`
  where the names go.
- **Cards** are drawn at a `form` that may change while shown. A
  `device.card` class may have a static `accepts(device)` to leave some of
  its devices to the app's own card.
- **`dashboard.card`**: each added card has its own `config`. Its `settings`
  element gets `host` and `config` and answers `change` with
  `detail: { config }`. Keep a working copy, since the `config` it is given
  lags behind its own saves.
- **`look.drawing`**: `draws` names families (`lights`, `switches`, `scenes`,
  `doors`, `readings`, `watching`, `media`, `climate`). It draws from `thing`
  and never commands a device; it asks with an `act` event,
  `detail: { do: 'switch' | 'run' | 'open' }`, and the app does it. It may
  be a Rive file instead of code (`"rive": "dial.riv", "values": 1`).
- **`look.piece`**: `draws` is `header` (given `room`) or `rest` (given
  `things`; may send a `wake` event).
- **`look.symbol`**: `symbols` lists names (lowercase, digits, hyphens); the
  element draws the one in `name` at `1em` in `currentColor`.
- **`app.assistant`**: draws all of its inside, including a way to close; it
  sends a `close` event to close. One plugin's at a time.

## A minimal element

Plain custom elements need no build tools. This one is a page that lists the
plugin's lights with a switch each (adapted from the template's
`ui/src/index.js`):

```js
class DemoPage extends HTMLElement {
  #host; #stop; devices = [];
  constructor() { super(); this.attachShadow({ mode: 'open' }); }

  set host(h) {
    if (this.#host === h) return;
    this.#host = h;
    this.shadowRoot.adoptedStyleSheets = [h.theme.sheet]; // the app's look
    this.#stop?.();
    this.#stop = h.devices.subscribe((list) => { this.devices = list; this.draw(); });
  }
  disconnectedCallback() { this.#stop?.(); }

  draw() {
    const h = this.#host;
    this.shadowRoot.innerHTML = `<section class="hc-card"><table class="hc-table">${
      this.devices.map((d) => `<tr><td></td><td><button class="hc-pill"></button></td></tr>`).join('')
    }</table></section>`;
    this.shadowRoot.querySelectorAll('tr').forEach((row, i) => {
      const d = this.devices[i];
      row.cells[0].textContent = h.devices.label(d);
      const b = row.querySelector('button');
      b.textContent = d.attributes.on ? 'Turn off' : 'Turn on';
      b.onclick = () => h.command(d.device_id, { action: 'toggle' });
    });
  }
}
customElements.define('hc-demo-page', DemoPage);
```

The theme sheet's classes: `hc-card`, `hc-head`, `hc-label`, `hc-num`,
`hc-quiet`, `hc-pill` (+ `go`, `danger`), `hc-field`, `hc-row`, `hc-grid`,
`hc-table`, `hc-tag` and `hc-dot` (+ `good`, `warn`, `bad`), and for cards
`hc-tile` (+ `compact`, `lit`) with `hc-tile-name` and `hc-tile-state`.

## Building

Use anything that makes custom elements: plain classes, Lit, or Svelte 5 with
`customElement`. Bundle everything into the one module. The template copies
`src/` and `public/manifest.json` into `dist/` with a small Node script;
hc-ecowitt uses Vite:

```js
// ui/vite.config.js
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte({ compilerOptions: { customElement: true } })],
  build: {
    lib: { entry: 'src/index.js', formats: ['es'], fileName: () => 'index.js' },
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
    cssCodeSplit: false,
  },
});
```

with `public/manifest.json` copied into `dist/`. The build must write
`dist/manifest.json`. Commit `ui/package-lock.json` (release builds run
`npm ci`).

Gotchas:

- In a Svelte custom element, a prop named `host` turns `$host()` into a
  store subscription. Destructure it as `let { host: hc } = $props()`.
- The app's global stylesheet doesn't reach a shadow root. Adopt
  `host.theme.sheet`. A CSS file imported from JS lands nowhere: import it
  with `?inline` and adopt it.
- A `@container` override must come after the rules it overrides.
- Don't assume `/api/v1` is proxied. Use `host.query`, `host.fetch` and the
  rest.
- Show readings in the person's units with `host.units.show` and convert
  input back with `host.units.toCore`. Values from homeCore are °C and
  metric.
- Show homeCore's alerts (`host.alerts`, such as `kind: 'low_battery'`)
  instead of deciding again from `battery_pct`. If a device needs an earlier
  warning, have the plugin publish `battery_low: true`.
- Escape every device name you put into markup, or set it with
  `textContent`.

## Developing

Build the UI (`npm run build`, or a watch build), then restart the plugin:
the new files get a new `build`, so the app loads them. Run the app against
a sandbox homeCore. Test screen logic with `vitest`. Look at screenshots at
desktop and phone widths, in light and dark, and check the fallback by
stopping the plugin.
