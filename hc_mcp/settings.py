"""The Assistant plugin's settings: the Claude API key, the model, what it may
do, and how long chats are kept.

Kept in ``settings.json`` in the plugin's data folder, readable by the plugin's
own user only, because it holds the key. Nothing here goes into homeCore's
plugin config: that file is shown to admins in the raw editor, and the key
must never reach a browser. ``public()`` is the only view the UI gets, and it
says only whether a key is set.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

#: (model id, what the settings page calls it). The first is the default.
MODELS: tuple[tuple[str, str], ...] = (
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
)
DEFAULT_MODEL = MODELS[0][0]

#: How long each person's chats are kept: (value, words). "none" keeps a chat
#: only while the plugin runs.
RETENTION: tuple[tuple[str, str], ...] = (
    ("30d", "30 days"),
    ("7d", "7 days"),
    ("none", "Don't keep"),
)
RETENTION_DAYS = {"30d": 30, "7d": 7, "none": 0}

#: The switches, by the registry category each turns on. Answering questions
#: is always on and has no switch.
SWITCHES = ("device_commands", "rule_mutations", "security", "plugin_actions")


@dataclass
class Settings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    device_commands: bool = True
    rule_mutations: bool = True
    #: Locks, doors and security: devices that count for security.
    security: bool = False
    #: Other plugins' actions. Off, and not on the settings page yet.
    plugin_actions: bool = False
    #: Ask before every change.
    confirm: bool = True
    retention: str = "30d"
    extra: dict = field(default_factory=dict)

    def enabled_categories(self) -> set[str]:
        return {name for name in SWITCHES if getattr(self, name)}

    def retention_days(self) -> int:
        return RETENTION_DAYS.get(self.retention, 30)

    def public(self) -> dict:
        """What the settings page may see. Never the key."""
        return {
            "api_key_set": bool(self.api_key),
            "model": self.model,
            "models": [{"id": m, "label": label} for m, label in MODELS],
            "device_commands": self.device_commands,
            "rule_mutations": self.rule_mutations,
            "security": self.security,
            "plugin_actions": self.plugin_actions,
            "confirm": self.confirm,
            "retention": self.retention,
            "retentions": [{"id": r, "label": label} for r, label in RETENTION],
        }


class SettingsStore:
    """Settings on disk, read once and written on every change."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._settings = self._load()

    def get(self) -> Settings:
        with self._lock:
            return Settings(**asdict(self._settings))

    def update(self, changes: dict) -> Settings:
        """Apply *changes* from the settings page and save.

        ``api_key`` sets the key (an empty string clears it); unknown fields
        and values outside the choices are refused with ``ValueError`` rather
        than saved, so a typo cannot quietly turn a switch off.
        """
        with self._lock:
            current = asdict(self._settings)
            for key, value in changes.items():
                if key == "api_key":
                    if not isinstance(value, str):
                        raise ValueError("api_key must be text")
                    current["api_key"] = value.strip()
                elif key == "model":
                    if value not in {m for m, _ in MODELS}:
                        raise ValueError(f"unknown model: {value}")
                    current["model"] = value
                elif key == "retention":
                    if value not in RETENTION_DAYS:
                        raise ValueError(f"unknown retention: {value}")
                    current["retention"] = value
                elif key in SWITCHES or key == "confirm":
                    if not isinstance(value, bool):
                        raise ValueError(f"{key} must be true or false")
                    current[key] = value
                else:
                    raise ValueError(f"unknown setting: {key}")
            self._settings = Settings(**current)
            self._save()
            return Settings(**asdict(self._settings))

    def _load(self) -> Settings:
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except FileNotFoundError:
            return Settings()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("cannot read %s (%s); starting from defaults", self.path, exc)
            return Settings()
        if not isinstance(raw, dict):
            return Settings()
        known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        try:
            return Settings(**known)
        except TypeError:
            return Settings()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = f"{self.path}.tmp"
        # Owner-only from the first byte: it holds the API key.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(self._settings), f, indent=2)
        os.replace(tmp, self.path)
