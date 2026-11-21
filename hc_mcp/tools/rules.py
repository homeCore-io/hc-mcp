"""Rule (automation) inspection + mutation tools.

Inspection tools (Phase 1) are unconditional. Mutation tools (Phase 2)
are gated behind ``HC_MCP_ALLOW_WRITE=rule_mutations`` (also satisfied
by ``HC_MCP_ALLOW_WRITE=all``).
"""

from __future__ import annotations

import httpx

from ..server_state import client

WRITE_CATEGORY = "rule_mutations"


def _wrap_http_error(label: str, e: httpx.HTTPStatusError) -> RuntimeError:
    return RuntimeError(
        f"{label} failed: HTTP {e.response.status_code} — {e.response.text or '(empty body)'}"
    )


async def list_rules() -> list[dict]:
    """All automations with their enabled flag, priority, trigger type,
    and any error state from disk parsing."""
    return await client().list_automations()


async def get_rule(rule_id: str) -> dict:
    """Full RON-equivalent JSON for one automation: trigger,
    conditions, and action sequence."""
    return await client().get_automation(rule_id)


async def rule_firings(rule_id: str, limit: int | None = None) -> list[dict]:
    """Recent fire history for an automation, oldest first. Each entry
    shows trigger match, per-condition outcome, and which actions ran.
    Useful when diagnosing "the rule never fires".

    homeCore keeps the last 20 runs of each rule; ``limit`` keeps only
    the newest N of those."""
    runs = await client().automation_history(rule_id)
    if limit is not None and isinstance(runs, list):
        runs = runs[-limit:] if limit > 0 else []
    return runs


async def rule_test(rule_id: str, at: str | None = None) -> dict:
    """Dry-run a rule against current device state without executing
    its actions. Returns which conditions pass/fail (with actual vs
    expected values + reason) and which actions would dispatch.
    Use this to verify a rule will fire BEFORE waiting for its
    trigger to occur naturally — much faster debug loop than
    watching `rule_firings` after-the-fact.

    ``at`` (RFC 3339, e.g. ``2026-11-21T22:30:00-05:00``) judges time
    conditions as of that moment instead of now, so "would it run at
    10:30 tonight?" can be asked now. Device conditions still read the
    current state."""
    return await client().test_automation(rule_id, at=at)


async def test_draft_rule(rule: dict, at: str | None = None) -> dict:
    """Dry-run a rule that isn't saved: the same report as ``rule_test``,
    for a body you are about to pass to ``create_rule`` or
    ``update_rule``. Nothing is saved and no action runs.

    Try a draft here first: it shows a trigger or condition that names a
    device that doesn't exist, or a check that can never pass, before
    the rule is live. ``at`` as for ``rule_test``."""
    try:
        return await client().test_draft_automation(rule, at=at)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("test_draft_rule", e) from e


# ── Mutations (Phase 2) ───────────────────────────────────────────────


async def enable_rule(rule_id: str) -> dict:
    """Enable an automation (PATCH /automations/{id} {enabled: true}).

    Idempotent — calling on an already-enabled rule is a no-op from
    the engine's perspective.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
    ``all``)."""
    try:
        return await client().enable_automation(rule_id)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("enable_rule", e) from e


async def disable_rule(rule_id: str) -> dict:
    """Disable an automation (PATCH /automations/{id} {enabled: false}).

    The rule stays on disk and can be re-enabled later. Use this for
    "pause for the weekend" patterns rather than `delete_rule`,
    which is destructive.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
    ``all``)."""
    try:
        return await client().disable_automation(rule_id)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("disable_rule", e) from e


async def delete_rule(rule_id: str) -> dict:
    """Permanently delete an automation (DELETE /automations/{id}).

    The rule file is removed and there is no undo. Read it with
    ``get_rule`` first if it might be wanted again, so its body can be
    passed back to ``create_rule``.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
    ``all``). Prefer `disable_rule` if you might want the rule
    back."""
    try:
        return await client().delete_automation(rule_id)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("delete_rule", e) from e


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
    try:
        return await client().create_automation(rule)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("create_rule", e) from e


async def update_rule(rule_id: str, rule: dict) -> dict:
    """Replace an automation's body (PUT /automations/{id}).

    Full replace — every field except the id is overwritten by what
    you pass. To change just one attribute (enabled, priority), use
    `enable_rule` / `disable_rule` / a future `set_priority` rather
    than reading + modifying + putting back. Try the new body with
    ``test_draft_rule`` first.

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=rule_mutations`` (or
    ``all``)."""
    try:
        return await client().update_automation(rule_id, rule)
    except httpx.HTTPStatusError as e:
        raise _wrap_http_error("update_rule", e) from e
