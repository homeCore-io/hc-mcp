"""Write-category gating.

Phase 1 ships read-only. Later phases (plugin actions, rule mutation,
device commands, plugin scaffolding) each declare a category name; the
operator opts in via ``HC_MCP_ALLOW_WRITE`` (comma-separated category
list, or ``all``).

Tools that perform writes call ``ensure_write(category)`` at entry and
raise a `PermissionError` if not enabled — FastMCP surfaces that as a
tool error so Claude sees the gating reason.
"""

from __future__ import annotations

import os


def allowed_categories() -> set[str]:
    raw = os.environ.get("HC_MCP_ALLOW_WRITE", "")
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    if "all" in parts:
        return {"all"}
    return parts


def is_allowed(category: str) -> bool:
    cats = allowed_categories()
    return "all" in cats or category in cats


def ensure_write(category: str) -> None:
    if not is_allowed(category):
        raise PermissionError(
            f"hc-mcp: write category '{category}' not enabled. "
            f"Set HC_MCP_ALLOW_WRITE={category} (or 'all') to permit it."
        )
