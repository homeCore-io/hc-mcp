# Python plugins

Read this when the plugin is in Python. The SDK is `homecore-plugin-sdk`,
imported as `homecore_plugin_sdk` (0.5.5 at the time of writing; Python 3.11
or newer). Source: [hc-plugin-sdk-py](https://github.com/homeCore-io/hc-plugin-sdk-py).
A real Python plugin with its own screens is
[hc-mcp](https://github.com/homeCore-io/hc-mcp) (`hc_mcp/plugin.py`, `ui/`).

Python plugins run in a **plugin runtime**, a container the operator runs,
not as children of homeCore. See `releasing.md`.

## Install

Nothing is on PyPI. Install from the GitHub repository at a tag, and check
the SDK's README for the current method first.

```toml
# pyproject.toml
[project]
dependencies = ["homecore-plugin-sdk>=0.5.5"]

[tool.uv.sources]
homecore-plugin-sdk = { git = "https://github.com/homeCore-io/hc-plugin-sdk-py", tag = "v0.5.5" }
```

or `pip install "git+https://github.com/homeCore-io/hc-plugin-sdk-py@v0.5.5"`.
With both repositories cloned side by side, `pip install -e ../hc-plugin-sdk-py`
links a local checkout instead. `caller`, `signed_in`, `api_scopes` and
`api_access` need 0.5.5 or newer.

## A minimal plugin

One lamp: an immediate `signed_in` action that reads `caller`, an admin
streaming action, REST access, an alert kind, a stop handler and its own
screens. It was checked against SDK 0.5.5 by driving the SDK's message
handler with a mocked MQTT client.

`demo_lamp/plugin.py` (with an empty `demo_lamp/__init__.py`):

```python
"""plugin.demo_lamp: one dimmable lamp. Run: python -m demo_lamp.plugin <config.toml>"""

import logging
import sys
import threading
import time

from homecore_plugin_sdk import (
    Action,
    AlertSeverity,
    Capabilities,
    PluginAlert,
    PluginAlertKind,
    PluginBase,
    PluginNotice,
    RequiresRole,
    ui,
)

__version__ = "0.1.0"
log = logging.getLogger("demo_lamp")
DEV = "demo_lamp"

# What the device reports and accepts (core's DeviceSchema), shared names only.
SCHEMA = {
    "attributes": {
        "on": {
            "kind": "bool",
            "writable": True,
            "display_name": "Power",
            "states": {
                "when_true": {"label": "on", "verb": "turns on"},
                "when_false": {"label": "off", "verb": "turns off"},
            },
        },
        "brightness_pct": {
            "kind": "float", "writable": True, "display_name": "Brightness",
            "unit": "%", "min": 0, "max": 100, "step": 1,
        },
    },
    "actions": [{"id": "toggle", "label": "Toggle", "sentence": "toggle {device}"}],
}


def capabilities() -> Capabilities:
    return Capabilities(
        actions=[
            Action(id="whoami", label="Who am I", description="Who is asking.",
                   requires_role=RequiresRole.SIGNED_IN, timeout_ms=5_000),
            Action(id="scan", label="Scan for lamps", description="Look for lamps.",
                   stream=True, cancelable=True, item_key="id",
                   requires_role=RequiresRole.ADMIN, timeout_ms=60_000),
        ],
        alert_kinds=[PluginAlertKind("lamp_hot", "Lamp running hot",
                                     severity=AlertSeverity.WARNING)],
        api_scopes=["devices:read"],
    )


class DemoLamp(PluginBase):
    PLUGIN_ID = "plugin.demo_lamp"  # from_config uses [homecore].plugin_id

    def __init__(self, **kw):
        super().__init__(**kw)
        self._lock = threading.Lock()
        self._on, self._pct = False, 100.0
        self._started = False

    def _state(self) -> dict:
        return {"on": self._on, "brightness_pct": self._pct if self._on else 0}

    # Runs on every (re)connect, on the MQTT thread.
    def on_connect(self):
        if not self._started:  # these add a thread or handler per call
            self._started = True
            self.enable_log_forwarding(min_level="INFO")
            self.enable_management(version=__version__, capabilities=capabilities())
        self.register_device_full(DEV, "Demo Lamp", device_type="light")
        self.register_device_schema(DEV, SCHEMA)
        with self._lock:
            self.publish_state(DEV, self._state())  # whole state, retained
        self.publish_availability(DEV, True)
        self.notices.clear("lamp_unreachable")

    # The MQTT thread: keep it quick, hand slow device I/O to a worker.
    def on_command(self, device_id, payload):
        with self._lock:
            if "action" in payload:
                if payload["action"] != "toggle":
                    log.warning("unknown action %s", payload["action"])
                    return
                self._on = not self._on
            if "on" in payload:
                self._on = bool(payload["on"])  # on: true keeps the last level
            if "brightness_pct" in payload:
                pct = max(0.0, min(100.0, float(payload["brightness_pct"])))
                self._on = pct > 0
                self._pct = pct or self._pct
            state = self._state()
        self.publish_state_partial_for_command(device_id, state, payload,
                                               fallback_source="demo")
        hot = state["brightness_pct"] >= 100
        # The whole list each time; an empty one clears.
        self.set_alerts(device_id, [PluginAlert("lamp_hot", "At full power")] if hot else [])

    def on_action(self, action, params, ctx=None, caller=None):
        if ctx is not None:  # streaming: its own thread, so blocking is fine
            for i in range(3):
                if ctx.is_canceled():
                    ctx.canceled()
                    return None
                ctx.progress(percent=i * 33, label="scanning")
                ctx.item_add({"id": f"lamp-{i}"})
                time.sleep(0.2)
            ctx.complete({"found": 3})
            return None
        if action == "whoami":  # immediate: return a dict
            scopes = (caller or {}).get("scopes", [])
            return {"username": (caller or {}).get("username"),
                    "can_command": "devices:command" in scopes}
        return None  # the SDK answers "unknown action"

    def on_stop(self):  # SIGTERM or Ctrl-C; about 1 second
        log.info("stopping")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    plugin = DemoLamp.from_config()  # argv[1]; exits with a message if bad
    d = ui.find_dir(__file__)
    if d:
        plugin.with_ui_dir(d, __version__)
    try:
        plugin.run()  # blocks until stopped
    except OSError as exc:
        log.error("cannot reach the broker: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The config file is the same for every SDK; `from_config()` reads `argv[1]`
and its `[homecore]` table (`broker_host`, `broker_port`, `plugin_id`,
`password`), and exits with a message when the file is missing or bad:

```toml
[homecore]
broker_host = "127.0.0.1"
broker_port = 1883
plugin_id   = "plugin.demo_lamp"
password    = ""
```

## Threads, not asyncio

The SDK is synchronous, on paho-mqtt's `loop_forever()`.

- `on_connect`, `on_command`, immediate `on_action`, `on_set_config` and
  `on_api_access` run on the MQTT thread. Blocking there stalls every
  command and the heartbeat. Hand slow device I/O to your own worker thread
  or queue.
- A streaming `on_action` runs on a thread of its own, so it may block. To
  use async code there, wrap it per call in `asyncio.run(...)`, as hc-mcp
  does.
- Never call `wait_for_api_access()` or `ctx.await_respond()` from the MQTT
  thread: the answer arrives on that same thread, so it deadlocks.
- `on_connect` runs on every reconnect. `enable_management` starts a
  heartbeat thread and `enable_log_forwarding` adds a log handler on each
  call, so guard them with a flag as the example does.
- Publishing before `run()` has created the client is dropped with a
  warning. Register and publish from `on_connect` or later.
- An immediate action's returned dict is merged into the response, so keys
  named `status` or `request_id` overwrite it. Avoid them.
- Guard your own device state with a lock; publishing is thread safe.

## The SDK's names

| Concept | Python SDK |
|---|---|
| Base class | `class X(PluginBase)` with `PLUGIN_ID = "plugin.x"`; `on_command` is required |
| Connect from config | `X.from_config()` (reads `argv[1]`); or `X(broker_host=, broker_port=, password=)` |
| Run loop | `plugin.run()`, blocks until stopped |
| Connected hook | `on_connect()` |
| Register | `register_device_full(id, name, device_type=, area=)`; also subscribes to its commands |
| Schema | `register_device_schema(id, schema_dict)`, core's `DeviceSchema` JSON (`attributes`, `actions`) |
| State | `publish_state(id, state)` (whole, retained), `publish_state_partial(id, patch)`, `publish_state_for_command(...)` and `publish_state_partial_for_command(id, state, cmd, fallback_source=)` |
| Availability | `publish_availability(id, bool)`; plugin status `publish_plugin_status("active")` |
| Commands | `on_command(device_id, payload)` |
| Management | `enable_management(interval_secs=60, version=, config_path=, capabilities=)` |
| Manifest | `Capabilities(actions=, config_schema=, config_descriptor=, alert_kinds=, api_scopes=)` |
| Action | `Action(id, label, description, params, result, stream, cancelable, concurrency, item_key, item_operations, requires_role, timeout_ms)` |
| Action handler | `on_action(self, action, params, ctx=None, caller=None)`; return a dict (immediate) or `None` (unknown, or streaming) |
| Stages | `ctx.progress(percent=, label=, message=, data=)`, `ctx.item_add/item_update/item_remove(data)`, `ctx.warning(msg)`, `ctx.awaiting_user(prompt, response_schema)` then `ctx.await_respond(timeout)`, `ctx.complete(data)`, `ctx.error(msg)`, `ctx.canceled()`, `ctx.is_canceled()` |
| Roles | `RequiresRole.ADMIN`, `USER` (default), `READ_ONLY`, `SIGNED_IN` |
| Caller | `caller=` keyword (immediate); `ctx.caller` (streaming); never in `params` |
| REST access | automatic: `self.api_access` (`.url` ends in `/api/v1`, `.key`, `.scopes`), `self.wait_for_api_access(timeout)`, hook `on_api_access(url, key, scopes)` |
| Settings | `config_schema` and `config_descriptor` on `Capabilities`; `on_set_config(config) -> bool` writes a form's changes (the SDK writes no TOML); `read_own_config()` |
| Notices | `self.notices.raise_(PluginNotice.warning(code, msg, remedy=))`, `.clear(code)`, `.set([...])` |
| Alerts | `PluginAlertKind(topic, label, severity=, default_on=)`; `set_alerts(id, [PluginAlert(topic, reason, key=, action=AlertAction(...))])`; `set_plugin_alerts` |
| Own screens | `ui.find_dir(__file__)` then `with_ui_dir(dir, version)` |
| Stop | `on_stop()`; the SDK handles SIGTERM and Ctrl-C when `run()` is on the main thread |
| Logs | `enable_log_forwarding(min_level="INFO")`; core's log-level changes set the root logger |
| Other devices | `subscribe_state(id)` with `on_state(device_id, state)` |

Files sent to actions, pictures the plugin keeps and async action handlers
are Rust only.

## Screens in a Python package

`ui.find_dir` looks at `HC_PLUGIN_UI_DIR`, then `ui/` inside the package, then
`ui/` beside the program, then `ui/dist` beside the nearest `pyproject.toml`.
Ship the built screens inside the wheel, as hc-mcp does:

```toml
[tool.hatch.build.targets.wheel.force-include]
"ui" = "hc_mcp/ui"
```

## Run and test

```bash
uv venv && uv pip install -e '.[dev]'
uv run python -m demo_lamp.plugin config/config.toml   # against a sandbox broker
uv run pytest -q
```

Unit tests need no broker. Replace the MQTT client with a mock and feed the
handler messages, as the SDK's and hc-mcp's own tests do:

```python
import json
from unittest.mock import MagicMock

from demo_lamp.plugin import DemoLamp

def msg(topic, body):
    m = MagicMock()
    m.topic, m.payload = topic, json.dumps(body).encode()
    return m

def test_brightness_100_raises_the_alert():
    p = DemoLamp(broker_host="127.0.0.1", broker_port=1883)
    p._client = MagicMock()
    p.on_connect()
    p._on_message_handler(msg("homecore/devices/demo_lamp/cmd", {"brightness_pct": 100}))
    topics = [c.args[0] for c in p._client.publish.call_args_list]
    assert "homecore/devices/demo_lamp/alerts" in topics
```

`_client` and `_on_message_handler` are private, so pin the SDK version your
tests were written against.

## Packaging

`[tool.homecore]` in `pyproject.toml` says what the runtime plugin is; the
release build reads it:

```toml
[tool.homecore]
id = "plugin.demo_lamp"          # required
entrypoint = "demo_lamp.plugin"  # required; run as python -m <entrypoint> <config>
name = "Demo Lamp"               # the Catalog's display name
category = "Lighting"
```

`homecore-plugin-sdk` must be in `[project].dependencies`. The release is
covered in `releasing.md`.
