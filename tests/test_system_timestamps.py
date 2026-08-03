"""Heartbeat-age arithmetic.

`system_health` decides a plugin has a stale heartbeat by comparing this
function's output against a threshold, so a parsing slip here shows up as a
plugin that is silently never reported stale — or one reported stale
constantly, off by the local UTC offset.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hc_mcp.tools.system import _seconds_since_iso

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC).timestamp()


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-08-03T11:59:00Z",  # homeCore's own format: RFC 3339, trailing Z
        "2026-08-03T11:59:00+00:00",
        "2026-08-03T07:59:00-04:00",  # same instant, different offset
    ],
)
def test_one_minute_ago_in_any_offset(stamp):
    assert _seconds_since_iso(stamp, NOW) == pytest.approx(60.0)


def test_naive_timestamps_are_read_as_utc():
    # Not local time — otherwise the age is wrong by the machine's offset,
    # which is how this kind of bug survives on a developer's laptop in UTC
    # and misbehaves everywhere else.
    assert _seconds_since_iso("2026-08-03T11:59:00", NOW) == pytest.approx(60.0)


def test_fractional_seconds_are_accepted():
    assert _seconds_since_iso("2026-08-03T11:59:00.500Z", NOW) == pytest.approx(59.5)


def test_a_future_timestamp_is_negative_not_clamped():
    assert _seconds_since_iso("2026-08-03T12:01:00Z", NOW) == pytest.approx(-60.0)


@pytest.mark.parametrize("bad", ["", "not-a-date", "2026-13-45T99:99:99Z", None])
def test_unparseable_input_is_none_rather_than_raising(bad):
    # A malformed heartbeat must not take down system_health, which reports
    # on every plugin at once.
    assert _seconds_since_iso(bad, NOW) is None
