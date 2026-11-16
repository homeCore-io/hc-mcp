"""Settings and chats on disk: the key never leaves, each person sees only
their own chats, and old chats go."""

from __future__ import annotations

import json
import os
import stat
import time

import pytest
from fakes import ADMIN, MEMBER

from hc_mcp.chats import Chat, ChatStore, new_chat_id, owner_key
from hc_mcp.settings import DEFAULT_MODEL, Settings, SettingsStore

# ── settings ────────────────────────────────────────────────────────────────


def test_defaults_match_the_settings_page(tmp_path):
    s = SettingsStore(str(tmp_path / "settings.json")).get()
    assert s.model == DEFAULT_MODEL == "claude-sonnet-5-5"
    assert (s.device_commands, s.rule_mutations, s.security, s.confirm) == (True, True, False, True)
    assert s.retention == "30d" and s.retention_days() == 30
    assert s.enabled_categories() == {"device_commands", "rule_mutations"}


def test_the_key_is_never_in_the_public_view(tmp_path):
    store = SettingsStore(str(tmp_path / "settings.json"))
    store.update({"api_key": "sk-ant-secret"})
    public = store.get().public()
    assert public["api_key_set"] is True
    assert "sk-ant-secret" not in json.dumps(public)
    assert "api_key" not in public


def test_settings_survive_a_restart_and_are_owner_only(tmp_path):
    path = str(tmp_path / "settings.json")
    SettingsStore(path).update({"api_key": " sk-ant-x ", "model": "claude-opus-5-5",
                                "security": True, "retention": "7d"})  # fmt: skip
    again = SettingsStore(path).get()
    assert (again.api_key, again.model, again.security, again.retention) == (
        "sk-ant-x", "claude-opus-5-5", True, "7d",
    )  # fmt: skip
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.parametrize(
    "change",
    [{"model": "gpt-5"}, {"retention": "forever"}, {"security": "yes"}, {"colour": True},
     {"api_key": 5}],
)  # fmt: skip
def test_bad_changes_are_refused_and_nothing_is_saved(tmp_path, change):
    store = SettingsStore(str(tmp_path / "settings.json"))
    with pytest.raises(ValueError):
        store.update(change)
    assert store.get() == Settings()
    assert not (tmp_path / "settings.json").exists()


def test_an_empty_key_clears_it(tmp_path):
    store = SettingsStore(str(tmp_path / "settings.json"))
    store.update({"api_key": "k"})
    store.update({"api_key": ""})
    assert store.get().public()["api_key_set"] is False


def test_a_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert SettingsStore(str(path)).get() == Settings()


# ── chats ───────────────────────────────────────────────────────────────────


def chat_for(caller: dict, title: str = "t", updated: float | None = None) -> Chat:
    c = Chat(id=new_chat_id(), owner=owner_key(caller), title=title)
    c.turns = [{"role": "user", "text": title}]
    return c


def test_each_person_sees_only_their_own(tmp_path):
    store = ChatStore(str(tmp_path))
    mine, theirs = chat_for(ADMIN, "mine"), chat_for(MEMBER, "theirs")
    store.save(mine, keep=True)
    store.save(theirs, keep=True)
    admin, member = owner_key(ADMIN), owner_key(MEMBER)
    assert [c["title"] for c in store.list(admin)] == ["mine"]
    assert [c["title"] for c in store.list(member)] == ["theirs"]
    # Not by asking for the other's id, nor deleting it.
    assert store.get(admin, theirs.id) is None
    assert store.delete(admin, theirs.id) is False
    assert store.get(member, theirs.id) is not None


def test_chats_are_kept_per_uid_on_disk(tmp_path):
    store = ChatStore(str(tmp_path))
    c = chat_for(ADMIN)
    store.save(c, keep=True)
    path = tmp_path / ADMIN["uid"] / f"{c.id}.json"
    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert ChatStore(str(tmp_path)).get(owner_key(ADMIN), c.id).turns == c.turns


def test_a_caller_without_a_uid_is_kept_by_name():
    assert owner_key({"uid": None, "username": "local admin", "kind": "local_admin"}) == (
        "name-local_admin"
    )
    assert owner_key(None) is None
    assert owner_key({"uid": None}) is None


def test_bad_ids_never_reach_the_disk(tmp_path):
    store = ChatStore(str(tmp_path))
    owner = owner_key(ADMIN)
    for bad in ("../../etc/passwd", "", None, "A" * 32):
        assert store.get(owner, bad) is None
        assert store.delete(owner, bad) is False


def test_retention_drops_old_chats(tmp_path):
    store = ChatStore(str(tmp_path))
    old, new = chat_for(ADMIN, "old"), chat_for(ADMIN, "new")
    store.save(old, keep=True)
    store.save(new, keep=True)
    # Age the first by rewriting its file.
    path = tmp_path / ADMIN["uid"] / f"{old.id}.json"
    raw = json.loads(path.read_text())
    raw["updated"] = time.time() - 31 * 86400
    path.write_text(json.dumps(raw))
    assert store.prune(30) == 1
    assert [c["title"] for c in store.list(owner_key(ADMIN))] == ["new"]
    assert store.prune(30) == 0


def test_seven_days_is_seven_days(tmp_path):
    store = ChatStore(str(tmp_path))
    c = chat_for(ADMIN)
    store.save(c, keep=True)
    assert store.prune(7, now=time.time() + 6 * 86400) == 0
    assert store.prune(7, now=time.time() + 8 * 86400) == 1


def test_dont_keep_writes_nothing_and_clears_what_was_kept(tmp_path):
    store = ChatStore(str(tmp_path))
    kept = chat_for(ADMIN, "kept")
    store.save(kept, keep=True)
    # Switched to "Don't keep": the next prune clears the disk...
    assert store.prune(0) == 1
    # ...and new chats live in memory only, still readable turn to turn.
    c = chat_for(ADMIN, "memory")
    store.save(c, keep=False)
    assert not (tmp_path / ADMIN["uid"] / f"{c.id}.json").exists()
    assert store.get(owner_key(ADMIN), c.id) is c
    assert [x["title"] for x in store.list(owner_key(ADMIN))] == ["memory"]
    # A day later even that is gone.
    assert store.prune(0, now=time.time() + 2 * 86400) == 1
    assert store.get(owner_key(ADMIN), c.id) is None
