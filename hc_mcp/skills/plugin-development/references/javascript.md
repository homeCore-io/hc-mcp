# JavaScript (Node.js) plugins

Read this when the plugin is in JavaScript. The SDK is the package
`homecore-plugin-sdk` (0.4.7 at the time of writing), CommonJS, Node 18 or
newer, with `mqtt` as its only dependency. Source:
[hc-plugin-sdk-js](https://github.com/homeCore-io/hc-plugin-sdk-js). It ships
JSDoc, no TypeScript types.

**Releasing:** a Node plugin reaches the Catalog as a pure-JavaScript package
for the Node.js plugin runtime, built by hc-scripts' `node-release.yml` from
a `homecore` block in `package.json`. See
[releasing.md](releasing.md#releasing-a-nodejs-plugin); hc-matter is the
working example.

## Install

Nothing is on npm. Install from the GitHub repository at a tag, and check the
SDK's README for the current method first:

```bash
npm install github:homeCore-io/hc-plugin-sdk-js#v0.4.7
npm install smol-toml        # the SDK has no TOML parser
```

With both repositories cloned side by side, `npm install ../hc-plugin-sdk-js`
links a local checkout instead. `caller`, `signed_in`, `apiScopes` and
`api_access` need 0.4.5 or newer; files sent to actions need 0.4.7.

## A minimal plugin

One lamp: an immediate `signed_in` action that reads `caller`, an admin
streaming action, REST access, an alert kind, a stop handler and its own
screens. It was checked against SDK 0.4.5 by driving it with a stand-in MQTT
client.

homeCore passes only the config file's path (`process.argv[2]`). Read the
broker settings from its `[homecore]` table and pass them to the constructor:

```toml
[homecore]
broker_host = "127.0.0.1"
broker_port = 1883
plugin_id   = "plugin.demo_lamp"
password    = ""
```

`plugin.js` (with a `package.json` that has a `version`):

```js
'use strict';
// plugin.demo_lamp: one dimmable lamp. Run: node plugin.js <config.toml>
const fs = require('node:fs');
const { parse } = require('smol-toml');
const {
  PluginBase, Capabilities, Action, RequiresRole,
  PluginAlert, PluginAlertKind, AlertSeverity, ui,
} = require('homecore-plugin-sdk');
const { version } = require('./package.json');

const DEV = 'demo_lamp';
const SCHEMA = {
  attributes: {
    on: {
      kind: 'bool', writable: true, display_name: 'Power',
      states: { when_true: { label: 'on', verb: 'turns on' },
                when_false: { label: 'off', verb: 'turns off' } },
    },
    brightness_pct: { kind: 'float', writable: true, display_name: 'Brightness',
                      unit: '%', min: 0, max: 100, step: 1 },
  },
  actions: [{ id: 'toggle', label: 'Toggle', sentence: 'toggle {device}' }],
};

class DemoLamp extends PluginBase {
  constructor(opts, configPath) {
    super(opts);
    this.configPath = configPath;
    this.lamp = { on: false, pct: 100 };
    this.started = false;
  }

  state() {
    return { on: this.lamp.on, brightness_pct: this.lamp.on ? this.lamp.pct : 0 };
  }

  // Every (re)connect. enableManagement starts a heartbeat timer per call: once.
  onConnect() {
    if (!this.started) {
      this.started = true;
      this.enableLogForwarding('info'); // logInfo/logWarn go nowhere without it
      const dir = ui.findDir(__dirname);
      if (dir) this.withUiDir(dir, version);
      this.enableManagement({
        version,
        configPath: this.configPath,
        capabilities: new Capabilities([
          new Action({ id: 'whoami', label: 'Who am I', description: 'Who is asking.',
                       requiresRole: RequiresRole.SIGNED_IN, timeoutMs: 5000 }),
          new Action({ id: 'scan', label: 'Scan for lamps', description: 'Look for lamps.',
                       stream: true, cancelable: true, itemKey: 'id',
                       requiresRole: RequiresRole.ADMIN, timeoutMs: 60000 }),
        ], {
          alertKinds: [new PluginAlertKind('lamp_hot', 'Lamp running hot',
                                           { severity: AlertSeverity.WARNING })],
          apiScopes: ['devices:read'],
        }),
      });
    }
    this.registerDeviceFull(DEV, 'Demo Lamp', { deviceType: 'light' }); // subscribes to cmd too
    this.registerDeviceSchema(DEV, SCHEMA);
    this.publishState(DEV, this.state()); // whole state, retained
    this.publishAvailability(DEV, true);
    this.notices.clear('lamp_unreachable');
  }

  // Called synchronously from the MQTT client: never throw out of here.
  onCommand(deviceId, cmd) {
    try {
      if (cmd.action !== undefined) {
        if (cmd.action !== 'toggle') throw new Error(`unknown action ${cmd.action}`);
        this.lamp.on = !this.lamp.on;
      }
      if ('on' in cmd) this.lamp.on = Boolean(cmd.on); // keeps the last level
      if ('brightness_pct' in cmd) {
        const pct = Math.min(100, Math.max(0, Number(cmd.brightness_pct)));
        this.lamp.on = pct > 0;
        if (pct > 0) this.lamp.pct = pct;
      }
    } catch (err) {
      this.logWarn(`command refused: ${err.message}`);
      return;
    }
    const state = this.state();
    this.publishStatePartialForCommand(deviceId, state, cmd, 'demo');
    // The whole list each time; an empty one clears.
    this.setAlerts(deviceId, state.brightness_pct >= 100
      ? [new PluginAlert('lamp_hot', 'At full power')] : []);
  }

  async onAction(action, params, ctx, caller) {
    if (ctx) { // streaming
      for (let i = 0; i < 3; i++) {
        if (ctx.isCanceled()) { ctx.canceled(); return; }
        ctx.progress({ percent: i * 33, label: 'scanning' });
        ctx.itemAdd({ id: `lamp-${i}` });
        await new Promise((r) => setTimeout(r, 200));
      }
      ctx.complete({ found: 3 });
      return;
    }
    if (action === 'whoami') {
      const scopes = caller ? caller.scopes : [];
      return { username: caller ? caller.username : null,
               can_command: scopes.includes('devices:command') };
    }
    return null; // the SDK answers "unknown action"
  }

  // `this.apiAccess` holds {url, key, scopes} too; url already ends in /api/v1.
  onApiAccess(url, key, scopes) {
    this.logInfo(`REST access to ${url} with ${scopes.join(', ')}`);
  }

  async onStop() { /* leave the device safe; about 1 second */ }
}

function main() {
  const configPath = process.argv[2];
  let hc;
  try {
    hc = parse(fs.readFileSync(configPath, 'utf8')).homecore;
  } catch (err) {
    console.error(`cannot read config ${configPath}: ${err.message}`);
    process.exit(1); // never die quietly
  }
  const plugin = new DemoLamp({
    pluginId: hc.plugin_id,
    brokerHost: hc.broker_host,
    brokerPort: hc.broker_port,
    password: hc.password,
  }, configPath);
  const client = plugin.run(); // SIGTERM and Ctrl-C are handled for you
  client.on('error', (err) => {
    if (err && (err.code === 4 || err.code === 5)) { // the broker refused the login
      console.error('broker refused the login');
      process.exit(1);
    }
  });
}

module.exports = { DemoLamp };
if (require.main === module) main();
```

Things the SDK leaves to you:

- `onConnect` runs on every reconnect, and each `enableManagement` call starts
  another heartbeat timer. Call it once, behind a flag.
- `onCommand` is called synchronously from the MQTT client, and a throw
  escapes into its event emitter. Catch everything inside it.
- `run()` returns the mqtt.js client and never rejects; mqtt.js retries a
  refused login forever. Watch `client.on('error')` and exit non-zero when
  the broker refuses you (CONNACK codes 4 and 5), so the supervisor shows why.
- Don't add your own SIGTERM or SIGINT handler: `run()` installs them and
  calls `stop()` (your `onStop`, then every device offline, the plugin
  offline, and exit).
- The schema is passed through as you write it. Use core's `DeviceSchema`
  JSON (`attributes` with `kind`, `writable`, `unit`, `min`, `max`, `states`;
  `actions` with `sentence`).

## The SDK's names

| Concept | JS SDK |
|---|---|
| Base class | `class X extends PluginBase`; `new X({ pluginId, brokerHost, brokerPort, password })` |
| Run loop | `plugin.run()`, returns the mqtt.js client and keeps the process alive |
| Connected hook | `onConnect()`, on every (re)connect |
| Register | `registerDeviceFull(id, name, { deviceType, area })`; also subscribes to its commands |
| Schema | `registerDeviceSchema(id, schema)` |
| State | `publishState(id, state)` (whole, retained), `publishStatePartial(id, patch)`, `publishStateForCommand` and `publishStatePartialForCommand(id, state, cmd, fallbackSource)` |
| Availability | `publishAvailability(id, bool)`; plugin status `publishPluginStatus('active')` |
| Commands | `onCommand(deviceId, payload)` |
| Management | `enableManagement({ intervalSecs, version, configPath, capabilities })` |
| Manifest | `new Capabilities(actions, { configSchema, configDescriptor, alertKinds, apiScopes })` |
| Action | `new Action({ id, label, description, params, result, stream, cancelable, concurrency, itemKey, itemOperations, requiresRole, timeoutMs })` |
| Action handler | `async onAction(action, params, ctx, caller)`; return an object (immediate) or `null` (unknown, or streaming) |
| Stages | `ctx.progress({ percent, label, message, data })`, `ctx.itemAdd/itemUpdate/itemRemove(data)`, `ctx.warning(msg, data)`, `ctx.awaitingUser(prompt, responseSchema)` then `await ctx.awaitRespond(ms)`, `ctx.complete(data)`, `ctx.error(msg)`, `ctx.canceled()`, `ctx.isCanceled()` |
| Roles | `RequiresRole.ADMIN`, `USER` (default), `READ_ONLY`, `SIGNED_IN` |
| Caller | fourth argument of `onAction`, and `ctx.caller`; never in `params` |
| REST access | automatic: `this.apiAccess` (`.url` ends in `/api/v1`, `.key`, `.scopes`), `await this.waitForApiAccess(ms)`, hook `onApiAccess(url, key, scopes)` |
| Settings | `configSchema` and `configDescriptor` on `Capabilities`; `onSetConfig(obj)` returns true once written |
| Notices | `this.notices.raise(PluginNotice.warning(code, msg, { remedy }))`, `.clear(code)`, `.set([...])` |
| Alerts | `new PluginAlertKind(topic, label, { severity, defaultOn })`; `setAlerts(id, [new PluginAlert(topic, reason, { key, action })])`; `setPluginAlerts` |
| Own screens | `ui.findDir(__dirname)` then `withUiDir(dir, version)` |
| Stop | `async onStop()` |
| Logs | `enableLogForwarding('info')`, then `logInfo/logWarn/logError(msg, fields)` |
| Other devices | `subscribeState(id)` with `onState(deviceId, state)` |

Pictures the plugin keeps and async action handlers are Rust only. A file
sent to an action (0.4.7) reaches the action as a local `file_path` param, as
in Rust, and is removed once the action replies. The `set_log_level` management action is accepted but has no
effect in this SDK.

## Run and test

```bash
node plugin.js config/config.toml        # against a sandbox broker
```

To let a sandbox homeCore run it, point `[[plugins]] binary` at an
executable that starts it, since homeCore runs `<binary> <config path>`:

```sh
#!/bin/sh
exec node /path/to/plugin.js "$1"
```

The SDK's own tests use jest with `jest.mock('mqtt')`; do the same for a
plugin: make `mqtt.connect` return an `EventEmitter` with `publish`,
`subscribe` and `end`, emit `connect`, then emit `message` events on
`homecore/devices/<id>/cmd` and `homecore/plugins/<plugin_id>/manage/cmd`
and assert on what was published.
