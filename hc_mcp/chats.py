"""Each person's chats, kept by the plugin and never by homeCore.

One folder per person (by homeCore user id), one JSON file per chat. A chat
holds two things:

- ``api_messages``: the conversation as the model's API takes it, appended to
  and never edited, so the next turn can carry on from it;
- ``turns``: the same conversation as the chat screen draws it (what was
  asked; the reply's text, steps, device cards and decisions).

How long chats are kept is a setting. "Don't keep" holds a chat in memory
only, for as long as the plugin runs (and a day at most), so a conversation
still works turn to turn but nothing is written down.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

_CHAT_ID = re.compile(r"^[0-9a-f]{32}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

#: A chat that is not written down is still dropped after a day.
MEMORY_ONLY_SECS = 24 * 3600


def owner_key(caller: dict | None) -> str | None:
    """Whose chats these are: homeCore's user id, else (a local admin or a
    whitelisted address, which have none) the name it gave. ``None`` when
    homeCore did not say who is asking."""
    if not isinstance(caller, dict):
        return None
    uid = caller.get("uid")
    if isinstance(uid, str) and uid:
        return _UNSAFE.sub("_", uid)
    name = caller.get("username")
    if isinstance(name, str) and name:
        return "name-" + _UNSAFE.sub("_", name)
    return None


def new_chat_id() -> str:
    return uuid.uuid4().hex


def valid_chat_id(chat_id: object) -> bool:
    return isinstance(chat_id, str) and bool(_CHAT_ID.match(chat_id))


@dataclass
class Chat:
    id: str
    owner: str
    title: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    api_messages: list = field(default_factory=list)
    turns: list = field(default_factory=list)

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "updated": self.updated}

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "turns": self.turns,
        }


class ChatStore:
    def __init__(self, root: str) -> None:
        self.root = root
        self._lock = threading.Lock()
        # Chats that are not written down ("Don't keep"), by (owner, id).
        self._memory: dict[tuple[str, str], Chat] = {}

    # ── reading ───────────────────────────────────────────────────────────

    def list(self, owner: str) -> list[dict]:
        out = {c.id: c.summary() for (o, _), c in self._memory_items() if o == owner}
        folder = self._folder(owner)
        try:
            names = os.listdir(folder)
        except FileNotFoundError:
            names = []
        for name in names:
            chat_id = name.removesuffix(".json")
            if not name.endswith(".json") or not valid_chat_id(chat_id):
                continue
            chat = self._read(owner, chat_id)
            if chat is not None:
                out[chat.id] = chat.summary()
        return sorted(out.values(), key=lambda c: c["updated"], reverse=True)

    def get(self, owner: str, chat_id: str) -> Chat | None:
        if not valid_chat_id(chat_id):
            return None
        with self._lock:
            held = self._memory.get((owner, chat_id))
        return held if held is not None else self._read(owner, chat_id)

    # ── writing ───────────────────────────────────────────────────────────

    def save(self, chat: Chat, *, keep: bool) -> None:
        """Keep *chat*: on disk when *keep*, else in memory only."""
        chat.updated = time.time()
        if not keep:
            with self._lock:
                self._memory[(chat.owner, chat.id)] = chat
            return
        with self._lock:
            self._memory.pop((chat.owner, chat.id), None)
        folder = self._folder(chat.owner)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        path = os.path.join(folder, f"{chat.id}.json")
        tmp = f"{path}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(chat), f)
        os.replace(tmp, path)

    def delete(self, owner: str, chat_id: str) -> bool:
        if not valid_chat_id(chat_id):
            return False
        with self._lock:
            found = self._memory.pop((owner, chat_id), None) is not None
        try:
            os.remove(os.path.join(self._folder(owner), f"{chat_id}.json"))
            found = True
        except FileNotFoundError:
            pass
        return found

    def prune(self, days: int, now: float | None = None) -> int:
        """Drop every chat older than *days* (by its last message); with 0,
        everything on disk, and memory-only chats older than a day. Returns
        how many went."""
        now = time.time() if now is None else now
        cutoff = now - days * 86400 if days > 0 else None
        gone = 0
        with self._lock:
            for key, chat in list(self._memory.items()):
                limit = cutoff if cutoff is not None else now - MEMORY_ONLY_SECS
                if chat.updated < limit:
                    del self._memory[key]
                    gone += 1
        try:
            owners = os.listdir(self.root)
        except FileNotFoundError:
            return gone
        for owner in owners:
            folder = os.path.join(self.root, owner)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(folder, name)
                if cutoff is not None:
                    chat = self._read(owner, name.removesuffix(".json"))
                    updated = chat.updated if chat else os.path.getmtime(path)
                    if updated >= cutoff:
                        continue
                try:
                    os.remove(path)
                    gone += 1
                except OSError as exc:
                    logger.warning("cannot remove old chat %s: %s", path, exc)
        return gone

    # ── internals ─────────────────────────────────────────────────────────

    def _memory_items(self) -> list[tuple[tuple[str, str], Chat]]:
        with self._lock:
            return list(self._memory.items())

    def _folder(self, owner: str) -> str:
        return os.path.join(self.root, _UNSAFE.sub("_", owner))

    def _read(self, owner: str, chat_id: str) -> Chat | None:
        path = os.path.join(self._folder(owner), f"{chat_id}.json")
        try:
            with open(path) as f:
                raw = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("cannot read chat %s: %s", path, exc)
            return None
        known = {k: v for k, v in raw.items() if k in Chat.__dataclass_fields__}
        try:
            chat = Chat(**known)
        except TypeError:
            return None
        # A file moved between folders is still only its folder's owner's.
        return chat if chat.owner == owner else None
