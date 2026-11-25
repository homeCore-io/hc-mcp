"""Tools only the in-app chat offers.

The MCP server keeps its tool list as it was; these exist because a person
chatting in the app sees a screen, not JSON:

- ``list_scenes`` / ``run_scene`` / ``list_rooms``: the plain household
  words, so "movie time" does not take three device reads.
- ``show_devices``: puts a list of devices on screen as a card ("Still on").
- ``suggest_replies``: one tap answers under the reply.

The two screen tools return what the chat draws; the chat loop turns that
into an item on the stream (see ``chat.py``).
"""

from __future__ import annotations

from ..server_state import client

#: Device types that count for security when the device has made no choice
#: itself, as the web app counts them (src/lib/security.ts).
SECURITY_TYPES = {
    "lock",
    "contact_sensor",
    "door",
    "window",
    "cover",
    "garage",
    "garage_door",
    "gate",
    "shade",
    "blind",
}


def is_security(device: dict) -> bool:
    """Whether a device counts for security: its own ``security`` choice
    when it has one, else its type."""
    choice = device.get("security")
    if choice is not None:
        return bool(choice)
    return (device.get("device_type") or "") in SECURITY_TYPES


def device_label(device: dict) -> str:
    return device.get("name_override") or device.get("name") or device.get("device_id", "")


def device_room(device: dict) -> str | None:
    return device.get("area_override") or device.get("area")


def describe_state(device: dict) -> str:
    """A device's state in a few words: "On, 80%", "Open", "Locked", "21.5 °C"."""
    a = device.get("attributes") or {}
    if not device.get("available", True):
        return "Not responding"
    if "locked" in a:
        return "Locked" if a["locked"] else "Unlocked"
    if "open" in a and isinstance(a["open"], bool):
        return "Open" if a["open"] else "Closed"
    if "on" in a and isinstance(a["on"], bool):
        if not a["on"]:
            return "Off"
        level = a.get("brightness_pct")
        return f"On, {round(level)}%" if isinstance(level, int | float) else "On"
    if isinstance(a.get("position"), int | float):
        return f"{round(a['position'])}% open"
    if isinstance(a.get("temperature"), int | float):
        return f"{round(a['temperature'], 1)} °C"
    if "motion" in a:
        return "Motion" if a["motion"] else "No motion"
    return ""


def is_lit(device: dict) -> bool:
    """Whether the state reads as on or open, for the card's warm color."""
    a = device.get("attributes") or {}
    return a.get("on") is True or a.get("open") is True or a.get("locked") is False


async def list_scenes() -> list[dict]:
    """Every scene in the house: id and name. Run one with ``run_scene``."""
    scenes = await client().list_scenes()
    return [{"id": s.get("id"), "name": s.get("name")} for s in scenes]


async def run_scene(scene_id: str) -> dict:
    """Run a scene by its id (from ``list_scenes``).

    Write-gated: requires ``HC_MCP_ALLOW_WRITE=device_commands`` (or
    ``all``); a scene that sets a lock, door or other device that counts for
    security also needs ``security`` in it."""
    return await client().activate_scene(scene_id)


async def list_rooms() -> list[dict]:
    """Every room (area) in the house, with its id and name."""
    areas = await client().list_areas()
    return [{"id": a.get("id"), "name": a.get("name")} for a in areas]


async def show_devices(title: str, device_ids: list[str]) -> dict:
    """Show the person a list of devices as a card, each with its room and
    state, for example the lights still on. Use this instead of writing a
    long list in the reply. ``title`` is a short heading ("Still on")."""
    wanted = list(dict.fromkeys(device_ids))
    by_id = {d.get("device_id"): d for d in await client().list_devices()}
    rows = []
    for device_id in wanted:
        d = by_id.get(device_id)
        if d is None:
            continue
        rows.append(
            {
                "device_id": device_id,
                "name": device_label(d),
                "room": device_room(d),
                "state": describe_state(d),
                "lit": is_lit(d),
            }
        )
    return {"title": title, "rows": rows, "missing": [i for i in wanted if i not in by_id]}


async def suggest_replies(options: list[str]) -> dict:
    """Offer the person up to three short replies they can tap, for example
    "Dim it at night instead". Call it at most once, at the end of a reply,
    and only when a follow up is likely."""
    return {"options": [o.strip() for o in options if o.strip()][:3]}
