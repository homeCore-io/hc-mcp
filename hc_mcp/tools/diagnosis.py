"""Diagnosis tools: where to look first when something in the house is wrong.

All read-only. Each wraps one homeCore endpoint (``plugin_health`` reads
the plugin list and puts the unhappy ones first) and returns what it says,
so the answers are homeCore's own.
"""

from __future__ import annotations

from typing import Any

from ..server_state import client

#: A plugin in one of these is doing its job.
_OK_STATUSES = {"active"}


async def plugin_health() -> dict:
    """Every plugin's health, the ones needing attention first.

    Each row: plugin_id, status (``active`` is running; ``offline``,
    ``not_responding``, ``degraded``, ``starting`` are not), enabled,
    version, device_count, restart_count, last_heartbeat, and its
    ``notices`` — what the plugin itself says is wrong, each with a level,
    code, message and the remedy it suggests. A plugin is listed under
    ``attention`` when it is turned on and not active, or has a notice.

    Start here when devices of one kind stop answering: the plugin behind
    them usually says why in its notices."""
    plugins = await client().list_plugins()
    rows = []
    for p in plugins:
        rows.append(
            {
                "plugin_id": p.get("plugin_id"),
                "status": p.get("status"),
                "enabled": p.get("enabled"),
                "version": p.get("version"),
                "device_count": p.get("device_count"),
                "restart_count": p.get("restart_count"),
                "last_heartbeat": p.get("last_heartbeat"),
                "notices": p.get("notices") or [],
            }
        )

    def needs_attention(r: dict) -> bool:
        down = r["enabled"] and r["status"] not in _OK_STATUSES
        return bool(down or r["notices"])

    attention = [r for r in rows if needs_attention(r)]
    return {
        "attention": attention,
        "ok": [r["plugin_id"] for r in rows if not needs_attention(r)],
        "total": len(rows),
    }


async def list_alerts() -> Any:
    """What needs attention now: the alerts homeCore is raising, most
    serious first, then newest.

    homeCore raises and clears them itself: something wet, smoke, a jammed
    lock, a low battery, a device offline for five minutes, an alert rule's
    time condition, or a plugin's own alert about its devices. Each has a
    kind, severity, device, message, when it was raised and whether it was
    acknowledged; a plugin's alert may carry an ``action`` (its button).
    Ignored alerts are left out."""
    return await client().get("/alerts")


async def audit_log(
    event_type: str | None = None,
    actor_id: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    result: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    limit: int = 50,
) -> Any:
    """Who changed what: homeCore's audit log, newest first.

    Every change made through the API is recorded: sign-ins, keys, users,
    devices, rooms, scenes, automations, plugin settings, backups. Filters,
    all optional:
      - event_type: such as ``automation.updated`` or ``auth.login``
      - actor_id:   the user or key owner's id
      - target_kind / target_id: what was changed (``automation`` and a
                    rule id, ``api_key``, ``user``, ``device``, ...)
      - result:     ``success``, ``denied`` or ``error``
      - from_ / to: RFC 3339 times
    Answers "who turned this automation off?" or "what changed last
    night?". Needs the audit:read scope."""
    return await client().get(
        "/audit",
        event_type=event_type,
        actor_id=actor_id,
        target_kind=target_kind,
        target_id=target_id,
        result=result,
        **{"from": from_},
        to=to,
        limit=max(1, min(limit, 500)),
    )


async def paused_rules() -> Any:
    """The automations another automation has paused: ``{paused: [rule ids]}``.

    A rule's PauseRule step pauses another until a ResumeRule step or a
    person resumes it; a paused rule doesn't run even though it is turned
    on, which is a common answer to "why didn't it run?". Pauses are kept
    in memory: a restart resumes them all."""
    return await client().get("/automations/paused")


async def stale_rule_refs() -> Any:
    """Automations that name devices homeCore no longer has, and which.

    A device that was removed or renamed leaves its id behind in rules
    that used it; those triggers never fire and those actions go nowhere.
    Another common answer to "why didn't it run?"."""
    return await client().get("/automations/stale-refs")


async def hub_variables() -> Any:
    """The hub variables automations have set, as they are now.

    Rules can set and test variables (counters, flags, last-seen times).
    A rule whose condition reads one behaves on its current value, so this
    shows what it saw. Variables live in memory: after a restart there are
    none until a rule sets one."""
    return await client().get("/automations/variables")


async def orphaned_devices() -> Any:
    """Devices homeCore holds that no plugin manages any more.

    Usually left behind by a plugin that was removed, or that renamed its
    devices. They never update, and automations that use them do nothing."""
    return await client().get("/devices/orphaned")


async def vocabulary_check() -> Any:
    """Automations, scenes and devices checked against what devices take.

    Finds commands and conditions that use a name or value a device doesn't
    accept, most serious first: ``broken`` (a device that isn't there, an
    action it never declared), ``undeclared`` (a key its schema doesn't
    have), ``rename`` (an old spelling, with what to use ``instead``) and
    ``unit`` (another unit, such as a temperature not in °C). Such a
    command is accepted and then does nothing, so this explains "the
    automation ran but the light didn't change". Changes nothing."""
    return await client().get("/system/vocabulary-check")


async def system_versions() -> Any:
    """Which version of everything is running: core, its parts, the web app
    and each plugin. Check it before reading a changelog or blaming a bug
    that a release fixed."""
    return await client().get("/system/versions")
