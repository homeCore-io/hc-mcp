# The chat's stream

How the Assistant's `chat` action talks to its screen (`hc-mcp-chat`, in
`ui/index.js`). The screen starts a reply with
`host.stream('chat', params, onEvent)` and answers a confirm card with
`host.respond(request_id, response)`. Everything below rides on the ordinary
streaming-action events the Python SDK's `StreamContext` emits
(`progress`, `item`, `warning`, `awaiting_user`, `complete`, `error`,
`canceled`), so homeCore passes it through untouched. The chat's own fields
are in each event's `data`.

Every event also carries `request_id` and `ts`; within one reply `ts` always
increases (the SDK makes sure), so a reader that drops repeated stamps loses
nothing.

## Starting a reply

`POST /plugins/plugin.mcp/command`, action `chat`:

```json
{ "text": "Is anything left on before bed?", "chat_id": "3f0c…(32 hex)", "units": "F" }
```

- `chat_id`: carry on an earlier chat; leave it out to start one.
- `units`: `F` or `C`, how the person reads temperatures (`host.units`).

homeCore adds who is asking (`caller`); the plugin never takes that from the
browser. The action is declared `requires_role: user`, so anyone signed in may
chat; the tools the model gets are only those the person's own scopes cover
and the settings allow.

## Parts

A reply is a list of parts, each with an `id` and a `kind`. The stream adds
and updates them (`item`, with the manifest's `item_key` `id`), and the stored
chat keeps the same list, so a chat opened later draws exactly what was seen.

| `kind` | Fields | Drawn as |
|---|---|---|
| `text` | `text` | The reply's words. Plain text with paragraphs, `- ` lists and `**bold**`. |
| `step` | `label`, `state` (`running`, `done`, `failed`) | A chip: "Looked at 42 devices". Added running, updated when done. |
| `devices` | `title`, `rows`: `[{device_id, name, room, state, lit}]` | A card listing devices ("Still on"). `lit` rows use the warm color. |
| `suggestions` | `options`: up to 3 strings | Buttons under the last reply; a tap sends that text. |
| `decided` | `title`, `outcome`, `text?`, `rule_id?` | What became of a confirm card. `outcome`: `done`, `declined`, `replied`, `expired`, `canceled`, `failed`. With `rule_id`, an "Open in editor" link. |
| `notice` | `text` | A quiet note: an API failure, "Stopped", "cut off". |

## Events

**Text as it is written**: `progress` with

```json
{ "stage": "progress", "data": { "kind": "text", "part": "a1b2c3d4e5f6", "delta": "Three lights " } }
```

Append `delta` to the `text` part `part`, creating it if new. Deltas come in
pieces of about 50 characters or every 80 ms.

**A part**: `item`, `op` `add` or `update`, `data` is the whole part:

```json
{ "stage": "item", "op": "add", "data": { "id": "9f8e7d6c5b4a", "kind": "step", "label": "Looking at devices", "state": "running" } }
{ "stage": "item", "op": "update", "data": { "id": "9f8e7d6c5b4a", "kind": "step", "label": "Looked at 42 devices", "state": "done" } }
```

**A confirm card**: `awaiting_user`. Sent before anything that changes the
house when "Ask before every change" is on. The reply waits (up to 10
minutes) for `host.respond`.

```json
{
  "stage": "awaiting_user",
  "prompt": "Turn off 3 lights",
  "response_schema": { "type": "object", "properties": { "choice": { "enum": ["cancel", "go"] }, "reason": { "type": "string" } }, "required": ["choice"] },
  "data": {
    "kind": "confirm",
    "id": "0a1b2c3d4e5f",
    "preview": { "id": "0a1b2c3d4e5f", "type": "devices", "title": "Turn off 3 lights", "detail": "Island pendants, Under cabinet, Floor lamp" },
    "choices": [ { "id": "cancel", "label": "Not now" }, { "id": "go", "label": "Turn them off", "primary": true } ]
  }
}
```

`preview.type`:

- `devices`: `title`, `detail` (the devices by name). A device command or
  several.
- `rule`: a draft automation. `title` (its name), `badge` ("Not saved"),
  `when`, `only_if`, `do` (lists of plain lines the model wrote for the
  person), `rule` (the automation as homeCore keeps it, for "show me exactly").
  A new one offers `save_off` ("Save, turned off") and `save_on` ("Save and
  turn on"); the person may also just type what to change.
- `plain`: `title`, `detail?`. A scene, turning an automation on or off,
  deleting one (its button has `danger: true`), another plugin's action.

Choices are drawn in the order given; `primary` is the accent button.

Answer with `host.respond(request_id, { "choice": "<id>" })`. `cancel` is
always accepted. When the person types a message while a card waits, the
screen answers `{ "choice": "cancel", "reason": "replied" }`, lets the reply
end, then sends the message: the model is told to wait for what they want
changed. Whatever the answer, a `decided` part follows with the same `id` as
the card.

**The end**:

- `complete`, `data`: `{ "chat_id", "title", "turn": { "role": "assistant", "parts": [...] } }`.
  Redraw the reply from `turn`; it is what was stored.
- `error`, `message`: in words for the person, for example
  "The assistant needs a Claude API key. An admin can add it in Settings >
  Plugins > Assistant." The stored chat has the same words as a `notice`.
- `canceled`: the person stopped it (`host.stream(...).cancel()`).
- `timeout` (from homeCore, after 15 minutes) and `busy` (from the app, a 409)
  are drawn as notes too.

## Other actions the screens use

All immediate; homeCore says who is asking, and each person sees only their
own chats.

| Action | Role | Params | Answer |
|---|---|---|---|
| `chats` | read_only | none | `{ ok, chats: [{id, title, updated}] }`, newest first |
| `chat_get` | read_only | `chat_id` | `{ ok, chat: {id, title, created, updated, turns} }` |
| `chat_delete` | read_only | `chat_id` | `{ ok }` |
| `settings_get` | admin | none | the settings below, plus `version` and `rest_access: {ready, scopes}` |
| `settings_set` | admin | any of the settings | `{ ok, ...settings }` or `{ ok: false, error }` |
| `test_key` | admin | `api_key?`, `model?` | `{ ok, message }` or `{ ok: false, error, reason }` |

Settings: `api_key` (write only; reads say only `api_key_set`), `model`
(`claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-4-5-20251001`; the
choices come back as `models`), `device_commands`, `rule_mutations`,
`security`, `confirm`, `plugin_actions` (true or false), `retention` (`30d`,
`7d`, `none`; choices as `retentions`).

A user turn in `turns` is `{ "role": "user", "text": "..." }`; an assistant
turn is `{ "role": "assistant", "parts": [...] }` as above.
