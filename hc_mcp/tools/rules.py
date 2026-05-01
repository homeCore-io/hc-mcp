"""Rule (automation) inspection + mutation tools.

Inspection tools (Phase 1) are unconditional. Mutation tools (Phase 2)
are gated behind ``HC_MCP_ALLOW_WRITE=rule_mutations`` (also satisfied
by ``HC_MCP_ALLOW_WRITE=all``).
"""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

from ..permissions import ensure_write
from ..server_state import client


WRITE_CATEGORY = "rule_mutations"


def _wrap_http_error(label: str, e: httpx.HTTPStatusError) -> RuntimeError:
    return RuntimeError(
        f"{label} failed: HTTP {e.response.status_code} — "
        f"{e.response.text or '(empty body)'}"
    )


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

    # ── Mutations (Phase 2) ───────────────────────────────────────────────

    @mcp.tool()
    async def enable_rule(rule_id: str) -> dict:
        """Enable an automation (PATCH /automations/{id} {enabled: true}).

        Idempotent — calling on an already-enabled rule is a no-op from
        the engine's perspective.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().enable_automation(rule_id)
        except httpx.HTTPStatusError as e:
            raise _wrap_http_error("enable_rule", e) from e

    @mcp.tool()
    async def disable_rule(rule_id: str) -> dict:
        """Disable an automation (PATCH /automations/{id} {enabled: false}).

        The rule stays on disk and can be re-enabled later. Use this for
        "pause for the weekend" patterns rather than `delete_rule`,
        which is destructive.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().disable_automation(rule_id)
        except httpx.HTTPStatusError as e:
            raise _wrap_http_error("disable_rule", e) from e

    @mcp.tool()
    async def delete_rule(rule_id: str) -> dict:
        """Permanently delete an automation (DELETE /automations/{id}).

        Core also patches any other rule files that reference this rule's
        devices, replacing each ref with a ``DELETED:`` placeholder, and
        returns ``{affected_rules: [...]}``. Inspect the returned list
        before assuming the deletion is consequence-free.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
        ``all``). Prefer `disable_rule` if you might want the rule
        back."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().delete_automation(rule_id)
        except httpx.HTTPStatusError as e:
            raise _wrap_http_error("delete_rule", e) from e

    @mcp.tool()
    async def create_rule(rule: dict) -> dict:
        """Create a new automation (POST /automations).

        ``rule`` is the full rule body matching the homeCore Rule struct:
        ``{name, enabled, priority, trigger, conditions, actions}``.
        Trigger / Condition / Action are tagged-enum JSON — see CLAUDE.md
        and ``get_rule(<existing_id>)`` for shape examples.

        ``id`` may be omitted or set to ``""`` — core will generate a
        UUID and return the saved rule including its new id.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().create_automation(rule)
        except httpx.HTTPStatusError as e:
            raise _wrap_http_error("create_rule", e) from e

    @mcp.tool()
    async def update_rule(rule_id: str, rule: dict) -> dict:
        """Replace an automation's body (PUT /automations/{id}).

        Full replace — every field except the id is overwritten by what
        you pass. To change just one attribute (enabled, priority), use
        `enable_rule` / `disable_rule` / a future `set_priority` rather
        than reading + modifying + putting back.

        Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
        ``all``)."""
        ensure_write(WRITE_CATEGORY)
        try:
            return await client().update_automation(rule_id, rule)
        except httpx.HTTPStatusError as e:
            raise _wrap_http_error("update_rule", e) from e
