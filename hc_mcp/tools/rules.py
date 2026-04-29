"""Rule (automation) inspection tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..server_state import client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_rules() -> list[dict]:
        """All automations with their enabled flag, priority, trigger type,
        and any error state from disk parsing."""
        return await client().list_automations()

    @mcp.tool()
    async def get_rule(rule_id: str) -> dict:
        """Full RON-equivalent JSON for one automation: trigger,
        conditions, and action sequence."""
        return await client().get_automation(rule_id)

    @mcp.tool()
    async def rule_firings(rule_id: str, limit: int | None = None) -> list[dict]:
        """Recent fire history for an automation. Each entry shows trigger
        match, per-condition outcome, and which actions ran. Useful when
        diagnosing "the rule never fires"."""
        return await client().automation_history(rule_id, limit=limit)

    @mcp.tool()
    async def rule_test(rule_id: str) -> dict:
        """Dry-run a rule against current device state without executing
        its actions. Returns which conditions pass/fail (with actual vs
        expected values + reason) and which actions would dispatch.
        Use this to verify a rule will fire BEFORE waiting for its
        trigger to occur naturally — much faster debug loop than
        watching `rule_firings` after-the-fact."""
        return await client().test_automation(rule_id)
