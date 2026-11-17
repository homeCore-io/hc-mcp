"""The skills: found, read, kept inside their folders, and offered as MCP
prompts and resources and in the chat's instructions."""

from __future__ import annotations

import asyncio

import pytest

from hc_mcp import guides
from hc_mcp.config import Config
from hc_mcp.homecore_client import HomeCoreClient
from hc_mcp.server import build_server
from hc_mcp.tools import skills as skill_tools

SKILL = """---
name: plug-ins
description: >
  Writes homeCore plugins.
  Use when someone asks how.
license: MIT
---

# Plugins

Read [python](references/python.md).
"""


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    d = tmp_path / "plug-ins"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL)
    (d / "references" / "python.md").write_text("# Python\n")
    (tmp_path / "secret.md").write_text("outside")
    (tmp_path / "not-a-skill").mkdir()
    monkeypatch.setattr(guides, "ROOT", tmp_path)
    guides.skills.cache_clear()
    yield tmp_path
    guides.skills.cache_clear()


def test_finds_skills_and_reads_front_matter(shelf):
    (s,) = guides.skills()
    assert s.name == "plug-ins"
    assert s.description == "Writes homeCore plugins. Use when someone asks how."
    assert s.files == ["SKILL.md", "references/python.md"]


def test_reads_files_and_body(shelf):
    assert guides.read("plug-ins", "references/python.md") == "# Python\n"
    assert guides.body("plug-ins").startswith("# Plugins")


def test_refuses_what_is_not_there_or_outside(shelf):
    with pytest.raises(LookupError, match="There are: plug-ins"):
        guides.read("nope")
    with pytest.raises(LookupError, match="It has: SKILL.md, references/python.md"):
        guides.read("plug-ins", "references/rust.md")
    with pytest.raises(ValueError):
        guides.read("plug-ins", "../secret.md")


def test_tools(shelf):
    listed = asyncio.run(skill_tools.list_skills())
    assert listed[0]["name"] == "plug-ins"
    assert asyncio.run(skill_tools.read_skill("plug-ins"))["text"] == SKILL
    assert "error" in asyncio.run(skill_tools.read_skill("plug-ins", "../secret.md"))


def test_server_offers_prompts_and_resources(shelf):
    client = HomeCoreClient(Config("http://127.0.0.1:1", "k", 1.0))
    mcp = build_server(client)
    prompts = asyncio.run(mcp.list_prompts())
    assert [p.name for p in prompts] == ["plug-ins"]
    msgs = asyncio.run(mcp.get_prompt("plug-ins", {}))
    assert "# Plugins" in msgs.messages[0].content.text
    uris = sorted(str(r.uri) for r in asyncio.run(mcp.list_resources()))
    assert uris == [
        "homecore-skill://plug-ins/SKILL.md",
        "homecore-skill://plug-ins/references/python.md",
    ]


def test_shipped_skills_are_well_formed():
    guides.skills.cache_clear()
    shipped = guides.skills()
    assert {s.name for s in shipped} >= {
        "dev-environment",
        "install-and-setup",
        "plugin-development",
    }
    for s in shipped:
        assert s.name == s.path.name
        assert 0 < len(s.description) <= 1024
