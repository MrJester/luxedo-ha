"""Schedule semantics and device state, including DST and unknown data."""

from datetime import UTC, datetime

import pytest

from custom_components.luxedo.api import LuxedoProtocolError
from custom_components.luxedo.models import build_devices, parse_schedules


def date(value):
    return datetime.fromisoformat(value)


def repeating(rule, duration="PT2H"):
    return {
        "events": [
            {
                "id": "r1",
                "project_id": 9,
                "name": "Show",
                "repeat": 1,
                "timing": {"rrule_string": rule, "duration_iso": duration},
            }
        ]
    }


def test_overnight_boundaries(timetables):
    schedule = parse_schedules(timetables["7"], {})[0]
    assert (
        len(
            schedule.occurrences(
                date("2026-10-11T00:00:00Z"), date("2026-10-12T00:00:00Z")
            )
        )
        == 1
    )
    assert (
        schedule.occurrences(date("2026-10-11T01:00:00Z"), date("2026-10-12T00:00:00Z"))
        == []
    )
    assert (
        schedule.occurrences(date("2026-10-10T00:00:00Z"), date("2026-10-10T23:00:00Z"))
        == []
    )


def test_utc_recurrence_stays_utc_across_dst():
    schedule = parse_schedules(
        repeating("DTSTART:20261031T230000Z\nRRULE:FREQ=DAILY;COUNT=3"), {}
    )[0]
    events = schedule.occurrences(
        date("2026-10-31T00:00:00Z"), date("2026-11-04T00:00:00Z")
    )
    assert len(events) == 3
    assert all(e.start.hour == 23 for e in events)


def test_timezone_recurrence_preserves_local_time():
    schedule = parse_schedules(
        repeating(
            "DTSTART;TZID=America/New_York:20261031T190000\nRRULE:FREQ=DAILY;COUNT=3"
        ),
        {},
    )[0]
    events = schedule.occurrences(
        date("2026-10-31T00:00:00Z"), date("2026-11-04T00:00:00Z")
    )
    assert [e.start.astimezone(UTC).hour for e in events] == [23, 0, 0]


def test_next_beyond_one_year_and_active():
    schedule = parse_schedules(
        repeating("DTSTART:20261010T230000Z\nRRULE:FREQ=YEARLY;COUNT=3"), {}
    )[0]
    now = date("2026-10-11T00:00:00Z")
    assert schedule.next_occurrence(now, active=True).start.year == 2026
    assert schedule.next_occurrence(now, active=False).start.year == 2027
    assert schedule.next_occurrence(date("2029-01-01T00:00:00Z"), active=False) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"events": "broken"},
        repeating("RRULE:FREQ=DAILY"),
        repeating("DTSTART:20261010T230000\nRRULE:FREQ=DAILY;COUNT=3"),
        repeating("DTSTART:20261010T230000Z\nRRULE:FREQ=DAILY", "P1M"),
        repeating("DTSTART:20261010T230000Z\nRRULE:FREQ=SECONDLY"),
    ],
)
def test_invalid_schedule_not_silently_empty(raw):
    with pytest.raises(LuxedoProtocolError):
        parse_schedules(raw, {})


def test_missing_vs_empty():
    assert parse_schedules(None, {}) is None
    assert parse_schedules({"events": []}, {}) == ()


def test_devices(startup, timetables):
    now = date("2026-10-10T20:00:00Z")
    device = build_devices(startup["device"], timetables, {"9": "Halloween"}, now)["7"]
    assert device.online is True
    assert device.current_show == "Halloween"
    assert device.next_show.summary == "Evening show"
    assert "secret" not in repr(device)
    startup["device"]["7"]["eidos"]["status"] = "LOST"
    device = build_devices(startup["device"], {}, {}, now)["7"]
    assert device.online is False
    assert device.current_show is None
    assert device.schedules is None


def test_bad_schedule_does_not_break_status(startup):
    device = build_devices(
        startup["device"], {"7": {"events": "bad"}}, {}, date("2026-10-10T20:00:00Z")
    )["7"]
    assert device.status == "PROJECT"
    assert device.schedule_error
    assert device.schedules is None


def test_duration_crossing_dst_is_elapsed_time():
    schedule = parse_schedules(
        repeating(
            "DTSTART;TZID=America/New_York:20261101T003000\nRRULE:FREQ=DAILY;COUNT=1"
        ),
        {},
    )[0]
    events = schedule.occurrences(
        date("2026-11-01T00:00:00Z"), date("2026-11-02T00:00:00Z")
    )
    assert events[0].end.astimezone(UTC) == date("2026-11-01T06:30:00Z")
    assert (
        schedule.next_occurrence(date("2026-11-01T06:00:00Z"), active=True).end
        == events[0].end
    )


@pytest.mark.parametrize(
    ("mutate", "field", "reason"),
    [
        (lambda e: e.pop("id"), "id", "missing_field_or_unknown_timezone"),
        (lambda e: e.update(repeat="1"), "repeat", "unsupported_repeat_flag"),
        (
            lambda e: e["timing"].update(duration_iso="PT0S"),
            "duration_iso",
            "nonpositive_duration",
        ),
        (
            lambda e: e["timing"].update(rrule_string="RRULE:FREQ=DAILY"),
            "rrule_string",
            "missing_dtstart",
        ),
        (
            lambda e: e["timing"].update(
                rrule_string="DTSTART:20261010T230000\nRRULE:FREQ=DAILY"
            ),
            "rrule_string",
            "missing_timezone",
        ),
    ],
)
def test_schedule_diagnostics_identify_field_without_values(
    startup, mutate, field, reason
):
    raw = repeating("DTSTART:20261010T230000Z\nRRULE:FREQ=DAILY;COUNT=3")
    event = raw["events"][0]
    event.update(
        name="private-show-title", id="private-id", project_id="private-project"
    )
    mutate(event)
    device = build_devices(
        startup["device"], {"7": raw}, {}, date("2026-10-10T20:00:00Z")
    )["7"]
    assert device.schedule_error
    details = device.schedule_error_details
    assert details["field"] == field
    assert details["reason"] == reason
    assert details["event_index"] == 0
    assert "private" not in str(details)
    assert "20261010" not in str(details)


def test_schedule_diagnostics_do_not_expose_invalid_value(startup):
    raw = repeating("private-malformed-rule-secret", "private-duration-secret")
    device = build_devices(
        startup["device"], {"7": raw}, {}, date("2026-10-10T20:00:00Z")
    )["7"]
    assert "secret" not in str(device.schedule_error_details)
    assert (
        device.schedule_error_details["event_format"]["timing"]["duration_iso"]["valid"]
        is False
    )
