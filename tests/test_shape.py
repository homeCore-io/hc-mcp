"""What the model reads of a long tool result."""

from __future__ import annotations

import json

from hc_mcp.chat import MAX_RESULT_CHARS, _shape


def device(i: int) -> dict:
    return {
        "device_id": f"dev_{i:03}",
        "name": f"Device {i}",
        "device_type": "light",
        "available": True,
        "attributes": {f"a{j}": "x" * 40 for j in range(8)},
    }


def test_a_long_device_list_names_every_device():
    # Whole, these are far past the limit; the last is what's looked for.
    devices = [device(i) for i in range(300)]
    out = json.loads(_shape("list_devices", devices))
    assert len(out["devices"]) == 300
    assert out["devices"][-1]["device_id"] == "dev_299"
    assert "attributes" not in out["devices"][0]
    assert "query" in out["note"]


def test_a_short_device_list_keeps_its_attributes():
    out = json.loads(_shape("list_devices", [device(1)]))
    assert out[0]["attributes"]["a0"] == "x" * 40


def test_any_long_list_is_cut_at_a_whole_entry_and_says_so():
    rows = [{"n": i, "text": "y" * 500} for i in range(200)]
    text = _shape("list_rules", rows)
    assert len(text) <= MAX_RESULT_CHARS
    out = json.loads(text)
    assert out["note"].startswith(f"The first {len(out['items'])} of 200")
    assert out["items"][-1]["text"] == "y" * 500
