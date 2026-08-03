"""Write gating.

Every mutating tool calls ``ensure_write(category)`` before it touches the
API, so this module is the only thing standing between an LLM and a real
device. It is worth testing precisely because it is small enough to look
obviously correct.
"""

from __future__ import annotations

import pytest

from hc_mcp import permissions


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("HC_MCP_ALLOW_WRITE", raising=False)


def test_default_denies_everything():
    assert permissions.allowed_categories() == set()
    assert not permissions.is_allowed("rule_mutations")
    with pytest.raises(PermissionError):
        permissions.ensure_write("rule_mutations")


def test_named_category_permits_only_itself(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "rule_mutations")
    assert permissions.is_allowed("rule_mutations")
    assert not permissions.is_allowed("device_commands")
    permissions.ensure_write("rule_mutations")
    with pytest.raises(PermissionError):
        permissions.ensure_write("device_commands")


def test_comma_separated_list(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "rule_mutations,device_commands")
    assert permissions.is_allowed("rule_mutations")
    assert permissions.is_allowed("device_commands")
    assert not permissions.is_allowed("plugin_actions")


def test_whitespace_is_tolerated(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "  rule_mutations ,  device_commands  ")
    assert permissions.is_allowed("rule_mutations")
    assert permissions.is_allowed("device_commands")


def test_all_is_a_wildcard(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "all")
    assert permissions.is_allowed("anything_at_all")
    permissions.ensure_write("device_commands")


def test_all_wins_when_mixed_with_names(monkeypatch):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", "rule_mutations,all")
    assert permissions.allowed_categories() == {"all"}
    assert permissions.is_allowed("device_commands")


@pytest.mark.parametrize("value", ["", "   ", ",", " , ,"])
def test_empty_and_degenerate_values_deny(monkeypatch, value):
    monkeypatch.setenv("HC_MCP_ALLOW_WRITE", value)
    assert permissions.allowed_categories() == set()
    assert not permissions.is_allowed("device_commands")


def test_denial_names_the_category_and_the_fix(monkeypatch):
    # The message is the only feedback the operator gets — it is surfaced
    # through the model, not a log they are reading.
    with pytest.raises(PermissionError) as e:
        permissions.ensure_write("device_commands")
    msg = str(e.value)
    assert "device_commands" in msg
    assert "HC_MCP_ALLOW_WRITE" in msg
