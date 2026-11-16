"""hc-mcp as a homeCore plugin: ``plugin.mcp``, the Assistant.

The same tools the MCP server serves, behind a chat in the homeCore app: an
"Ask" button on every page opens it (the plugin's ``hc-mcp-chat`` element, slot
``app.assistant``), and its settings page is ``hc-mcp-settings``
(``plugin.page``).

Run it the way homeCore runs every plugin, with its config file as argv[1]::

    python -m hc_mcp.plugin /path/to/config.toml      # in a Python runtime
    hc-mcp plugin /path/to/config.toml                # by hand

Nothing to paste: homeCore mints the plugin a REST key on every start (it asks
for one with ``api_scopes``) and says who is asking with every action. The
plugin never goes beyond that person's own scopes.

Where it keeps things (the API key, chats): its data folder, in order
``HC_MCP_DATA_DIR``; ``[assistant].data_dir`` in the config; for a plugin in a
runtime (config at ``.../plugins/plugin.mcp/<version>/config.toml``) the
plugin's own folder above the versions, ``.../plugins/plugin.mcp/data``, so an
upgrade keeps them; else ``hc-mcp-data`` beside the config file.

It never dies of a missing key, an API failure or REST access that has not
arrived: it logs it, says so on its page (a notice) and in the chat.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time

from homecore_plugin_sdk import (
    Action,
    Capabilities,
    Concurrency,
    PluginBase,
    PluginNotice,
    RequiresRole,
    StreamContext,
    ui,
)

from . import __version__
from .chat import Turn
from .chats import Chat, ChatStore, new_chat_id, owner_key, valid_chat_id
from .config import Config
from .homecore_client import HomeCoreClient
from .provider import AnthropicProvider, Provider, ProviderError
from .server_state import using_client
from .settings import SettingsStore

logger = logging.getLogger("hc_mcp.plugin")

PLUGIN_ID = "plugin.mcp"

#: What the plugin asks homeCore's REST API for. homeCore never grants
#: users:write or api_keys:admin to a plugin, and the chat offers a person
#: only the tools their own scopes cover.
API_SCOPES = [
    "devices:read",
    "automations:read",
    "scenes:read",
    "areas:read",
    "devices:command",
    "scenes:run",
    "automations:write",
    "plugins:read",
    "plugins:write",
    "audit:read",
]

NO_ACCESS = (
    "The assistant is still waiting for homeCore to give it access to the house. "
    "If this lasts more than a minute, restart the Assistant in Settings > Plugins."
)
NO_CALLER = "homeCore didn't say who is asking, so the assistant can't answer. Update homeCore."
NOT_ADMIN = "Only an admin can change the assistant's settings."

#: How long a chat waits for REST access that has not arrived yet.
ACCESS_WAIT_SECS = 5.0
#: How often old chats are cleared out.
PRUNE_EVERY_SECS = 3600

_OWNER = {"type": "string"}
_CHAT_ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}


def capabilities() -> Capabilities:
    return Capabilities(
        api_scopes=list(API_SCOPES),
        actions=[
            Action(
                id="chat",
                label="Ask",
                description="Send a message to the assistant and stream its reply.",
                params={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "chat_id": _CHAT_ID,
                        "units": {"type": "string", "enum": ["F", "C"]},
                    },
                    "required": ["text"],
                },
                stream=True,
                cancelable=True,
                concurrency=Concurrency.MULTI,
                item_key="id",
                requires_role=RequiresRole.SIGNED_IN,
                # Long enough for a confirm card to wait for its answer.
                timeout_ms=15 * 60 * 1000,
            ),
            Action(
                id="chats",
                label="Past chats",
                description="Your own chats with the assistant, newest first.",
                requires_role=RequiresRole.SIGNED_IN,
            ),
            Action(
                id="chat_get",
                label="Open a chat",
                description="One of your own chats.",
                params={"type": "object", "properties": {"chat_id": _CHAT_ID},
                        "required": ["chat_id"]},
                requires_role=RequiresRole.SIGNED_IN,
            ),
            Action(
                id="chat_delete",
                label="Delete a chat",
                description="Delete one of your own chats.",
                params={"type": "object", "properties": {"chat_id": _CHAT_ID},
                        "required": ["chat_id"]},
                requires_role=RequiresRole.SIGNED_IN,
            ),
            Action(
                id="settings_get",
                label="Assistant settings",
                description="The model, what the assistant may do, how long chats are kept.",
                requires_role=RequiresRole.ADMIN,
            ),
            Action(
                id="settings_set",
                label="Change assistant settings",
                description="Change the API key, model, switches or chat retention.",
                params={"type": "object"},
                requires_role=RequiresRole.ADMIN,
            ),
            Action(
                id="test_key",
                label="Test the key",
                description="Check that the Claude API key and model work.",
                params={"type": "object", "properties": {"api_key": {"type": "string"},
                                                         "model": {"type": "string"}}},
                requires_role=RequiresRole.ADMIN,
                timeout_ms=30_000,
            ),
        ],
    )  # fmt: skip


def data_dir_for(config_path: str | None, own: dict | None = None) -> str:
    """Where the plugin keeps its settings and chats (see the module docs)."""
    env = os.environ.get("HC_MCP_DATA_DIR")
    if env:
        return env
    configured = ((own or {}).get("assistant") or {}).get("data_dir")
    base = os.path.dirname(os.path.abspath(config_path)) if config_path else os.getcwd()
    if configured:
        return configured if os.path.isabs(configured) else os.path.join(base, configured)
    version_dir, plugin_dir = base, os.path.dirname(base)
    if os.path.basename(plugin_dir) == PLUGIN_ID and os.path.basename(version_dir):
        return os.path.join(plugin_dir, "data")
    return os.path.join(base, "hc-mcp-data")


def ui_dir() -> str | None:
    """The UI folder: a runtime's, the one installed in the package, or the
    source tree's ``ui/``."""
    found = ui.find_dir(__file__)
    if found:
        return found
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
    return here if os.path.isfile(os.path.join(here, "manifest.json")) else None


class AssistantPlugin(PluginBase):
    PLUGIN_ID = PLUGIN_ID

    #: Builds the model client; tests swap it.
    provider_factory = staticmethod(
        lambda settings, api_key=None, model=None: AnthropicProvider(
            api_key if api_key is not None else settings.api_key, model or settings.model
        )
    )
    #: Builds the homeCore client from the REST access; tests swap it.
    client_factory = staticmethod(
        lambda access: HomeCoreClient(
            Config(base_url=access.url.removesuffix("/api/v1"), api_key=access.key,
                   timeout_secs=10.0)
        )
    )  # fmt: skip

    def __init__(self, data_dir: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data_dir = data_dir
        self._stores_ready = threading.Lock()
        self._settings: SettingsStore | None = None
        self._chats: ChatStore | None = None
        self._last_prune = 0.0
        self._forwarding_logs = False

    # ── stores ────────────────────────────────────────────────────────────

    def _ensure_stores(self) -> None:
        with self._stores_ready:
            if self._settings is not None:
                return
            root = self._data_dir or data_dir_for(self._bootstrap_config_path, self._own_config())
            os.makedirs(root, mode=0o700, exist_ok=True)
            logger.info("Assistant data folder: %s", root)
            self._settings = SettingsStore(os.path.join(root, "settings.json"))
            self._chats = ChatStore(os.path.join(root, "chats"))

    @property
    def settings(self) -> SettingsStore:
        self._ensure_stores()
        assert self._settings is not None
        return self._settings

    @property
    def chats(self) -> ChatStore:
        self._ensure_stores()
        assert self._chats is not None
        return self._chats

    def _own_config(self) -> dict:
        try:
            return self.read_own_config()
        except (OSError, ValueError):
            return {}

    def _prune(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_prune < PRUNE_EVERY_SECS:
            return
        self._last_prune = now
        gone = self.chats.prune(self.settings.get().retention_days(), now=now)
        if gone:
            logger.info("Cleared %d old chats", gone)

    def _refresh_notices(self) -> None:
        if not self.settings.get().api_key:
            self.notices.raise_(
                PluginNotice.warning(
                    "no_api_key",
                    "The assistant has no Claude API key, so the chat can't answer.",
                    remedy="Add a key from console.anthropic.com on this page.",
                )
            )
        else:
            self.notices.clear("no_api_key")
        if self.api_access is None:
            self.notices.raise_(
                PluginNotice.info(
                    "no_rest_access",
                    "Waiting for homeCore to give the assistant access to the house.",
                )
            )
        else:
            self.notices.clear("no_rest_access")

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_connect(self) -> None:
        if not self._forwarding_logs:
            # Here rather than before run(): a log line sent before the
            # broker connection exists would be logged as a warning, which
            # would be sent, which would be logged...
            self._forwarding_logs = True
            self.enable_log_forwarding()
        self.enable_management(version=__version__, capabilities=capabilities())
        self.publish_plugin_status("active")
        self._prune(force=True)
        self._refresh_notices()

    def on_command(self, device_id: str, payload: dict) -> None:
        # The assistant has no devices of its own.
        logger.debug("ignoring a command for %s", device_id)

    def on_api_access(self, url: str, key: str, scopes: list[str]) -> None:
        logger.info("REST access from homeCore at %s", url)
        self._refresh_notices()

    # ── actions ───────────────────────────────────────────────────────────

    def on_action(self, action, params, ctx=None, caller=None):
        if ctx is not None:
            caller = ctx.caller
            if action == "chat":
                self._chat(ctx, params)
            return None

        if action in ("settings_get", "settings_set", "test_key"):
            if caller is not None and caller.get("role") != "admin":
                return {"ok": False, "error": NOT_ADMIN}
            if action == "settings_get":
                return self._settings_view()
            if action == "settings_set":
                try:
                    self.settings.update(params or {})
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
                self._refresh_notices()
                self._prune(force=True)
                return {"ok": True, **self._settings_view()}
            return self._test_key(params or {})

        if action in ("chats", "chat_get", "chat_delete"):
            owner = owner_key(caller)
            if owner is None:
                return {"ok": False, "error": NO_CALLER}
            self._prune()
            if action == "chats":
                return {"ok": True, "chats": self.chats.list(owner)}
            chat_id = (params or {}).get("chat_id")
            if action == "chat_get":
                chat = self.chats.get(owner, chat_id) if valid_chat_id(chat_id) else None
                if chat is None:
                    return {"ok": False, "error": "No such chat."}
                return {"ok": True, "chat": chat.public()}
            return {"ok": self.chats.delete(owner, chat_id)}
        return None

    def _settings_view(self) -> dict:
        access = self.api_access
        return {
            **self.settings.get().public(),
            "version": __version__,
            "rest_access": {
                "ready": access is not None,
                "scopes": list(access.scopes) if access else [],
            },
        }

    def _test_key(self, params: dict) -> dict:
        settings = self.settings.get()
        key = params.get("api_key") or settings.api_key
        try:
            provider = self.provider_factory(settings, api_key=key, model=params.get("model"))
            asyncio.run(provider.check())
        except ProviderError as exc:
            return {"ok": False, "error": str(exc), "reason": exc.reason}
        return {"ok": True, "message": "The key works."}

    def _chat(self, ctx: StreamContext, params: dict) -> None:
        owner = owner_key(ctx.caller)
        if owner is None:
            ctx.error(NO_CALLER)
            return
        text = (params.get("text") or "").strip()
        if not text:
            ctx.error("Type a message first.")
            return
        settings = self.settings.get()
        try:
            provider: Provider = self.provider_factory(settings)
        except ProviderError as exc:
            logger.warning("chat refused: %s", exc)
            self._refresh_notices()
            ctx.error(str(exc))
            return
        access = self.api_access or self.wait_for_api_access(ACCESS_WAIT_SECS)
        if access is None:
            logger.warning("chat refused: no REST access from homeCore yet")
            ctx.error(NO_ACCESS)
            return

        self._prune()
        keep = settings.retention_days() > 0
        chat_id = params.get("chat_id")
        chat = self.chats.get(owner, chat_id) if valid_chat_id(chat_id) else None
        if chat is None:
            chat = Chat(id=new_chat_id(), owner=owner)

        turn = Turn(
            ctx=ctx,
            provider=provider,
            settings=settings,
            caller=ctx.caller or {},
            chat=chat,
            units=params.get("units"),
            save=lambda c: self.chats.save(c, keep=keep),
            key_scopes=list(access.scopes),
        )

        async def run() -> dict:
            hc = self.client_factory(access)
            try:
                with using_client(hc):
                    return await turn.run(text)
            finally:
                await hc.aclose()

        out = asyncio.run(run())
        if "error" in out:
            ctx.error(out["error"])
        elif out.get("stopped"):
            ctx.canceled()
        else:
            ctx.complete(out)


def main(config_path: str | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("HC_MCP_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    path = config_path or (sys.argv[1] if len(sys.argv) > 1 else None)
    plugin = AssistantPlugin.from_config(path)
    found = ui_dir()
    if found:
        plugin.with_ui_dir(found, __version__)
    else:
        logger.warning("No UI folder found; the app will show no chat")
    plugin.run()


if __name__ == "__main__":
    main()
