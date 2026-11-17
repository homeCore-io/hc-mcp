"""homeCore's skills: how-to guides for setting up, using and building for
homeCore, from the homeCore-io/skills repo.

A copy ships inside the package (``hc_mcp/skills``, refreshed with
``scripts/sync-skills.sh``). Each skill is a folder with a ``SKILL.md`` (YAML
front matter with ``name`` and ``description``, then the guide) and
``references/*.md`` it links to for detail.

The MCP server offers them three ways: a prompt per skill, a resource per
file, and the ``list_skills`` / ``read_skill`` tools. The in-app chat names
them in its instructions and reads one with ``read_skill`` when a question
needs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).parent / "skills"

#: Resource URIs: homecore-skill://<skill>/<file>, e.g.
#: homecore-skill://plugin-development/references/python.md
SCHEME = "homecore-skill"

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path

    @property
    def files(self) -> list[str]:
        """Every Markdown file in the skill, SKILL.md first, as paths
        relative to the skill's folder."""
        rest = sorted(
            p.relative_to(self.path).as_posix()
            for p in self.path.rglob("*.md")
            if p.name != "SKILL.md"
        )
        return ["SKILL.md", *rest]


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    """The front matter's top-level ``key: value`` pairs, and the body.

    Enough YAML for what a SKILL.md carries: plain scalars, quoted or not,
    and folded (``>``) or literal (``|``) blocks.
    """
    m = _FRONT.match(text)
    if not m:
        return {}, text
    out: dict[str, str] = {}
    key = None
    block: list[str] = []
    for line in m.group(1).splitlines():
        top = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if top:
            if key and block:
                out[key] = " ".join(s.strip() for s in block if s.strip())
            key, value = top.group(1), top.group(2).strip()
            block = []
            if value in (">", "|", ">-", "|-"):
                continue
            out[key] = value.strip("\"'")
            key = None if value else key
        elif key:
            block.append(line)
    if key and block:
        out[key] = " ".join(s.strip() for s in block if s.strip())
    return out, text[m.end() :]


@cache
def skills() -> tuple[Skill, ...]:
    """The skills that ship with this package, by name."""
    found = []
    if ROOT.is_dir():
        for d in sorted(ROOT.iterdir()):
            md = d / "SKILL.md"
            if not md.is_file():
                continue
            meta, _ = _front_matter(md.read_text(encoding="utf-8"))
            found.append(
                Skill(
                    name=meta.get("name") or d.name,
                    description=meta.get("description", ""),
                    path=d,
                )
            )
    return tuple(found)


def find(name: str) -> Skill | None:
    return next((s for s in skills() if s.name == name), None)


def read(name: str, file: str = "SKILL.md") -> str:
    """One file of a skill. Raises ``LookupError`` with what does exist when
    the skill or file isn't there, and ``ValueError`` for a path that leaves
    the skill's folder."""
    skill = find(name)
    if skill is None:
        have = ", ".join(s.name for s in skills()) or "none"
        raise LookupError(f"No skill named {name!r}. There are: {have}.")
    target = (skill.path / file).resolve()
    if not target.is_relative_to(skill.path.resolve()):
        raise ValueError(f"{file!r} is outside the skill.")
    if not target.is_file() or target.suffix != ".md":
        raise LookupError(f"{name} has no {file!r}. It has: {', '.join(skill.files)}.")
    return target.read_text(encoding="utf-8")


def body(name: str) -> str:
    """A skill's SKILL.md without its front matter."""
    return _front_matter(read(name))[1].lstrip()


def uri(name: str, file: str = "SKILL.md") -> str:
    return f"{SCHEME}://{name}/{file}"
