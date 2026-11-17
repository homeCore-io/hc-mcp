# Actions, roles, callers and REST access

Read this when you add an action to a plugin, decide who may run it, or need
the plugin to call homeCore's own REST API. The types are in
`crates/hc-types/src/plugin_capabilities.rs` in the homeCore repository.
Public page: [Plugin Capabilities & Actions](https://homecore.io/docs/plugins/capabilities).

## Two kinds of action

- **Device actions** are things a device does that are not an attribute
  write: `toggle`, `apply_preset`, `take_snapshot`. They go in the device's
  schema (`actions`, each with a `sentence` such as `"toggle {device}"` so
  automations read naturally) and arrive as a device command,
  `{"action": "toggle", ...params}`, on the command callback.
- **Plugin actions** are things the plugin itself does: pair a bridge, rescan,
  install firmware, answer a chat. They go on the **capability manifest** and
  arrive on the management channel, through the SDK's action handler. The web
  app lists them on the plugin's page, and hc-mcp offers them as tools.

The rest of this page is about plugin actions.

## Declaring one

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Stable snake_case id. |
| `label` | required | Button text. |
| `description` | | Help text in the app and in MCP. |
| `params` | | A JSON-schema subset: `type`, `default`, `enum`, `required`, `minimum`, `maximum`, `description`. The app also reads `title`, `x-options` (labels for `enum` values), and hides strings marked `format: "password"` or `writeOnly`. |
| `result` | | Advisory shape of the reply or of `complete.data`. |
| `stream` | `false` | Emits stages over time. |
| `cancelable` | `false` | The app offers Cancel while it runs. |
| `concurrency` | `multi` | `single` answers a second run with `busy` and the running `request_id`. |
| `item_key`, `item_operations` | | For `item` stages: the field in `data` the app dedupes by, and which of `add`, `update`, `remove` it emits. |
| `requires_role` | `user` | Who may run it (below). |
| `timeout_ms` | 5 s | How long core waits for the reply; for a stream, the deadline after which core ends it with `timeout`. **Always set it.** 5 s fails anything that talks to hardware. |
| `danger` | `false` | Can't be undone, or interrupts the house. Screens ask first. |

Adding an action needs no change to core, the SDKs, the app or hc-mcp.

## Immediate and streaming

**Immediate** (`stream: false`): one request, one reply.

```bash
curl -s -X POST "$HC/api/v1/plugins/plugin.demo/command" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "whoami"}'
```

Whatever the plugin replies, its own `status: "error"` included, comes back
with HTTP 200. Core answers 504 only when the plugin doesn't reply within
`timeout_ms`. In Rust, answer an action that talks to a device with
`with_async_handler`, never by blocking `with_custom_handler`.

**Streaming** (`stream: true`): the POST returns
`{request_id, status: "accepted", stream_topic}` at once, and the stages
follow over SSE:

```bash
curl -sN -H "Authorization: Bearer $TOKEN" \
  "$HC/api/v1/plugins/plugin.demo/command/$REQUEST_ID/stream"
```

The plugin publishes them on
`homecore/plugins/{plugin_id}/commands/{request_id}/events`, retained, and
the SDK clears that topic when the action ends.

### Stages

| Stage | Ends it | Meaning |
|---|---|---|
| `progress` | no | `percent`, `label`, `message`. |
| `item` | no | `op` (`add`, `update`, `remove`) and `data`, keyed by `item_key`. |
| `awaiting_user` | no | A `prompt` and an optional `response_schema`; the client answers with `respond`. |
| `warning` | no | Recoverable; the flow continues. |
| `complete` | yes | Success, with `data` shaped like `result`. |
| `error` | yes | Unrecoverable failure. |
| `canceled` | yes | Sent by the action itself once it has seen the cancel and cleaned up. The SDK never sends it for you. |
| `timeout` | yes | Sent by core when `timeout_ms` passes. |

Rules: the six plugin stages are a closed set, and plugin data goes in
`data`. `error` is always terminal; retries are `warning`. Emit exactly one
terminal stage. If a handler returns without one, the SDK sends `error`
(`data.reason: "plugin_dropped_stream"`). Core ends every open stream with
`error` (`data.reason: "plugin_offline"`) when the plugin goes offline.

Answer a prompt, or cancel, with a command naming the run:

```json
{"action": "respond", "target_request_id": "<id>", "response": {"name": "Lamp"}}
{"action": "cancel", "target_request_id": "<id>"}
```

The SDKs handle `respond` and `cancel`: the action reads the answer with
`await_respond` and checks `is_canceled()` between steps.

## Who may run it: `requires_role`

| Value | Who |
|---|---|
| `user` (default) | Callers with `plugins:write`. An action left off the manifest is treated the same. |
| `read_only` | `plugins:write` on `command`. It also answers on `POST /plugins/{id}/query`, which needs only `devices:read`. Use it for catalogues and status your screens read. |
| `admin` | `plugins:write` and the admin role. |
| `signed_in` | Every signed-in person or key, whatever their role, a household member included, through `command` and `upload`. |

`signed_in` is opt-in. Use it only for an action that is safe for anyone in
the house, or one that limits itself by `caller`. A `signed_in` action's
stream, and its `respond` and `cancel`, belong to whoever started it (and to
admins).

Core enforces the role before forwarding. Under `signed_in` the plugin must
still keep within the caller's scopes.

## Who asked: `caller`

Every action core forwards (`command`, `query`, `upload`) carries the
verified caller. Core drops any `caller` a client put in the body first, so
the plugin can trust it:

```jsonc
{
  "uid": "8c1f...",            // null for local_admin, whitelist, and a plugin's own key
  "username": "ann",
  "role": "household_member",  // the role's wire name: admin, user, read_only, household_member, ...
  "scopes": ["devices:read", "devices:command", "scenes:run"],
  "kind": "user"               // user | api_key | local_admin | whitelist
}
```

- For an API key, judge by `scopes`. A key's `role` says little.
- Do for a caller only what their scopes allow. The scopes are
  `devices:read`, `devices:write`, `devices:command`, `scenes:read`,
  `scenes:write`, `scenes:run`, `automations:read`, `automations:write`,
  `areas:read`, `areas:write`, `plugins:read`, `plugins:write`,
  `content:read`, `content:write`, `users:read`, `users:write`,
  `audit:read`, `api_keys:admin`.
- Key per-person data by `uid`, falling back to `username` where `uid` is
  null.

Where each SDK puts it:

| SDK | Immediate | Streaming |
|---|---|---|
| Rust | `Caller::from_cmd(cmd)` in the custom or async handler | `ctx.caller()` |
| Python | `caller=` keyword of `on_action` | `ctx.caller` |
| JavaScript | fourth argument of `onAction` | `ctx.caller` (and the fourth argument) |
| .NET | fourth argument of `OnActionWithCaller` | `ctx.Caller` (and the fourth argument) |

Every SDK removes `caller` from a streaming action's `params` (Rust since
0.6.5).

## The plugin's own REST access: `api_scopes` and `api_access`

A plugin that needs homeCore's REST API (to read automations, say) lists the
scopes on its manifest:

```json
{"spec": "1", "plugin_id": "plugin.demo", "actions": [...], "api_scopes": ["devices:read"]}
```

Then, each time the manifest is published (every start), core makes the
plugin an API key with those scopes and sends it as the management action
`api_access` with `{url, key, scopes}`:

- `url` is homeCore's REST base as the plugin reaches it, ending in
  `/api/v1`: the address its runtime was added with, or loopback for a
  plugin core runs. Call it with `Authorization: Bearer <key>`.
- `users:write` and `api_keys:admin` are never granted.
- Keep the key in memory only. The previous key stops working when a new one
  is made, and the key is deleted when the plugin is uninstalled.
- A plugin that does not answer `api_access`, or answers with an error, has
  its key deleted; its next start brings a new one.
- The key shows in the API keys list as `plugin <id>`, and in the audit log
  as `api_key:plugin <id>`.

Every SDK answers `api_access` for you and keeps the access (Rust
`mgmt.api_access()` since 0.6.5, Python `api_access`, JavaScript
`apiAccess`, .NET `ApiAccess`), with a wait helper and a hook. In Rust, a
custom handler that still answers `api_access` keeps working: the SDK keeps
the grant first, and that handler's reply is what core gets.

## Files sent to an action (Rust only)

`POST /plugins/{id}/upload/{action}` sends a file of up to 32 MiB to one of
the manifest's actions. The SDK receives it in pieces and runs the action
with a local `file_path` param, then removes the file once the action has
replied. Copy it first if a streaming action keeps working after replying.
From a screen: `host.upload(action, file, params)`; the params arrive as
strings. Example: hc-wled's `install_firmware_file`.

## Checks

In Rust, `conformance::check_manifest(&caps)` (part of `check_all`) flags an
action that inherits the 5 s timeout by accident, and
`check_actions_routed(&caps, &["id", ...])` fails when the manifest and your
handler disagree in either direction. Do the same check by hand in other
languages: every declared id is handled, and every handled id is declared.
