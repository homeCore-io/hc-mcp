"""homeCore's how-to guides (skills): setting up a dev environment,
installing and configuring homeCore, and writing plugins."""

from __future__ import annotations

from .. import guides


async def list_skills() -> list[dict]:
    """List homeCore's how-to guides (skills): each one's name, what it
    covers and the files it has. Read one with read_skill."""
    return [
        {"name": s.name, "description": s.description, "files": s.files} for s in guides.skills()
    ]


async def read_skill(name: str, file: str = "SKILL.md") -> dict:
    """Read one of homeCore's how-to guides before answering a question it
    covers: installing or upgrading homeCore, configuring it, adding plugins,
    plugin runtimes or users, setting up a development environment, or
    writing a plugin. Start with SKILL.md; it says which file under
    references/ to read for more detail on a step."""
    try:
        text = guides.read(name, file)
    except (LookupError, ValueError) as exc:
        return {"error": str(exc)}
    return {"name": name, "file": file, "text": text}
