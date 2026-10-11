"""Validated device and schedule models, independent of Home Assistant."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from isodate import parse_duration

from .api import LuxedoProtocolError

MAX_OCCURRENCES = 10000


@dataclass(frozen=True)
class Occurrence:
    """One calendar occurrence; all dates are aware."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    show_id: str
    priority: int | None


@dataclass(frozen=True)
class Schedule:
    """A portal timetable entry, preserving the server recurrence semantics."""

    uid: str
    summary: str
    show_id: str
    priority: int | None
    start: datetime | None = None
    end: datetime | None = None
    rule: str | None = None
    duration: timedelta = timedelta()

    def occurrences(self, start: datetime, end: datetime) -> list[Occurrence]:
        """Expand only the requested window, including overlapping events."""
        if self.rule:
            rule = rrulestr(self.rule, tzids=ZoneInfo)
            starts = rule.xafter(start - self.duration, inc=True)
        else:
            starts = iter([self.start])
        result = []
        for index, when in enumerate(starts):
            if when is None or when >= end:
                break
            if index >= MAX_OCCURRENCES:
                raise LuxedoProtocolError("Calendar query exceeds occurrence limit")
            until = self._end(when) if self.rule else self.end
            if until is not None and until > start:
                result.append(
                    Occurrence(
                        self.uid, self.summary, when, until, self.show_id, self.priority
                    )
                )
        return result

    def _end(self, start: datetime) -> datetime:
        """Durations are elapsed time, including across DST transitions."""
        return (start.astimezone(UTC) + self.duration).astimezone(start.tzinfo)

    def next_occurrence(self, now: datetime, *, active: bool) -> Occurrence | None:
        """Find the current/next occurrence without a fixed lookahead horizon."""
        if not self.rule:
            if self.start is None or self.end is None:
                return None
            if self.end > now if active else self.start >= now:
                return Occurrence(
                    self.uid,
                    self.summary,
                    self.start,
                    self.end,
                    self.show_id,
                    self.priority,
                )
            return None
        rule = rrulestr(self.rule, tzids=ZoneInfo)
        lower = now - self.duration if active else now
        for when in islice(rule.xafter(lower, inc=True), 2):
            until = self._end(when)
            if until > now:
                return Occurrence(
                    self.uid, self.summary, when, until, self.show_id, self.priority
                )
        return None


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # No local-time guess: device timezone has not been verified.
        raise ValueError("Schedule date has no timezone")
    return parsed


class LuxedoScheduleError(LuxedoProtocolError):
    """A schedule rejection with static, non-personal diagnostic details."""

    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__("Unsupported Luxedo timetable format")
        self.details = details


def _value_format(value: Any) -> dict[str, Any]:
    """Describe a value without exporting its text, dates, names or identifiers."""
    result: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, str):
        result["length"] = len(value)
        result["has_outer_whitespace"] = value != value.strip()
        try:
            result["datetime_has_timezone"] = (
                datetime.fromisoformat(value).tzinfo is not None
            )
        except ValueError:
            pass
    return result


def _timing_format(event: Any) -> dict[str, Any]:
    """Only inspect known schema fields; never return arbitrary keys or values."""
    if not isinstance(event, dict):
        return _value_format(event)
    result = {}
    for key in ("id", "project_id", "repeat", "timing"):
        result[key] = _value_format(event[key]) if key in event else {"missing": True}
    repeat = event.get("repeat")
    result["repeat"]["supported_value"] = repeat in (0, 1, False, True)
    timing = event.get("timing")
    if isinstance(timing, dict):
        for key in ("t_start", "t_end", "rrule_string", "duration_iso"):
            result["timing"][key] = (
                _value_format(timing[key]) if key in timing else {"missing": True}
            )
        rule = timing.get("rrule_string")
        if isinstance(rule, str):
            result["timing"]["rrule_string"].update(
                {
                    "has_dtstart": "DTSTART" in rule,
                    "has_tzid": "TZID=" in rule,
                    "has_until": "UNTIL=" in rule,
                    "has_count": "COUNT=" in rule,
                    "has_literal_newline_escape": "\\n" in rule,
                }
            )
        duration = timing.get("duration_iso")
        if isinstance(duration, str):
            try:
                parsed = parse_duration(duration)
                result["timing"]["duration_iso"]["fixed_duration"] = isinstance(
                    parsed, timedelta
                )
                if isinstance(parsed, timedelta):
                    result["timing"]["duration_iso"]["positive"] = parsed > timedelta()
            except (ValueError, TypeError, OverflowError):
                result["timing"]["duration_iso"]["valid"] = False
    return result


def _normalize_portal_rrule(rule: str) -> str:
    """Match Luxedo's JS UTC parsing for recurrence dates without a TZID.

    Its bundled untilStringToDate uses Date.UTC for DTSTART and UNTIL with
    or without a trailing Z. dateutil instead treats unmarked dates as naive.
    Explicit TZID rules retain their original wall-clock semantics.
    """
    if re.search(r"\bTZID=", rule, flags=re.IGNORECASE):
        return rule

    def utc_date(match: re.Match[str]) -> str:
        value = match[2]
        if len(value) == 8:
            value += "T000000"
        return f"{match[1]}{value}Z"

    return re.sub(
        r"\b(DTSTART[:=]|UNTIL=)(\d{8}(?:T\d{6})?)(?=$|[;\r\n])",
        utc_date,
        rule,
        flags=re.IGNORECASE | re.MULTILINE,
    )


def parse_schedules(raw: Any, shows: dict[str, str]) -> tuple[Schedule, ...] | None:
    """Null/missing timetable is unknown; an explicit empty list is empty."""
    if raw is None:
        return None
    field = "events"
    reason = "invalid_value"
    event_index = None
    event = None
    try:
        events = raw["events"]
        if not isinstance(events, list):
            reason = "expected_list"
            raise ValueError
        result = []
        for index, event in enumerate(events):
            event_index = index
            field, reason = "timing", "invalid_value"
            timing = event["timing"]
            field = "project_id"
            show_id = str(event["project_id"])
            field = "id"
            common = dict(
                uid=str(event["id"]),
                summary=event.get("name") or shows.get(show_id, "Luxedo show"),
                show_id=show_id,
                priority=event.get("priority"),
            )
            field = "repeat"
            repeat = event.get("repeat", 0)
            if repeat not in (0, 1, False, True):
                reason = "unsupported_repeat_flag"
                raise ValueError
            if repeat:
                field = "rrule_string"
                rule_text = timing["rrule_string"]
                if "DTSTART" not in rule_text:
                    reason = "missing_dtstart"
                    raise ValueError
                if "FREQ=SECONDLY" in rule_text:
                    reason = "unsupported_frequency"
                    raise ValueError
                reason = "invalid_recurrence_rule"
                rule_text = _normalize_portal_rrule(rule_text)
                rule = rrulestr(rule_text, tzids=ZoneInfo)
                first = next(iter(rule), None)
                if first is not None and first.tzinfo is None:
                    reason = "missing_timezone"
                    raise ValueError
                field, reason = "duration_iso", "invalid_duration"
                duration = parse_duration(timing["duration_iso"])
                if not isinstance(duration, timedelta):
                    reason = "variable_length_duration"
                    raise ValueError
                if duration <= timedelta():
                    reason = "nonpositive_duration"
                    raise ValueError
                result.append(Schedule(**common, rule=rule_text, duration=duration))
            else:
                field, reason = "t_start", "invalid_datetime_or_missing_timezone"
                start = _date(timing["t_start"])
                field = "t_end"
                end = _date(timing["t_end"])
                if end <= start:
                    reason = "end_not_after_start"
                    raise ValueError
                result.append(Schedule(**common, start=start, end=end))
        return tuple(result)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as err:
        if isinstance(err, KeyError):
            reason = "missing_field_or_unknown_timezone"
        details = {
            "event_index": event_index,
            "field": field,
            "reason": reason,
            "exception_type": type(err).__name__,
            "timetable_type": type(raw).__name__,
            "event_format": _timing_format(event),
        }
        raise LuxedoScheduleError(details) from err


@dataclass(frozen=True)
class Device:
    """Only the non-secret device fields needed by entities."""

    id: str
    name: str
    model: str
    firmware: str | None
    status: str | None
    online: bool | None
    current_show: str | None
    schedules: tuple[Schedule, ...] | None
    schedule_error: bool = False
    schedule_error_details: dict[str, Any] | None = None
    next_show: Occurrence | None = None
    calendar_event: Occurrence | None = None


def parse_device(
    raw: dict[str, Any], timetable: Any, shows: dict[str, str], now: datetime
) -> Device:
    """Interpret observed RPi fields, leaving unsupported states unknown."""
    try:
        eidos = raw.get("eidos") or {}
        status = eidos.get("status") or raw.get("status")
        model = raw["type_id"]
        online = None
        if model in ("dev_luxedo", "dev_luxcast"):
            if status in {"IDLE", "PROJ_TT", "PROJECT", "PNC"}:
                online = True
            elif status in {"OFF", "LOST", "NEW"}:
                online = False
        player = eidos.get("player") or {}
        show_id = player.get("id", eidos.get("proj_id"))
        current_show = None
        if status in {"PROJECT", "PROJ_TT"} and show_id is not None:
            current_show = shows.get(str(show_id), f"Show {show_id}")
        schedule_error = False
        schedule_error_details = None
        try:
            schedules = parse_schedules(timetable, shows)
            upcoming = [
                event
                for s in schedules or ()
                if (event := s.next_occurrence(now, active=False))
            ]
            calendar = [
                event
                for s in schedules or ()
                if (event := s.next_occurrence(now, active=True))
            ]
        except LuxedoProtocolError as err:
            schedules, upcoming, calendar, schedule_error = None, [], [], True
            if isinstance(err, LuxedoScheduleError):
                schedule_error_details = err.details
        return Device(
            id=str(raw["id"]),
            name=raw.get("name") or "Luxedo projector",
            model=model,
            firmware=raw.get("version_crnt"),
            status=status,
            online=online,
            current_show=current_show,
            schedules=schedules,
            schedule_error=schedule_error,
            schedule_error_details=schedule_error_details,
            next_show=min(upcoming, key=lambda e: e.start, default=None),
            calendar_event=min(calendar, key=lambda e: e.start, default=None),
        )
    except (KeyError, TypeError, AttributeError) as err:
        raise LuxedoProtocolError("Unsupported Luxedo device format") from err


def build_devices(
    raw: dict[str, Any],
    timetables: dict[str, Any],
    shows: dict[str, str],
    now: datetime,
) -> dict[str, Device]:
    """Run recurrence computations off the HA event loop."""
    if not isinstance(raw, dict) or not isinstance(timetables, dict):
        raise LuxedoProtocolError("Invalid device or timetable collection")
    devices = {}
    for item in raw.values():
        if not isinstance(item, dict) or "id" not in item:
            raise LuxedoProtocolError("Invalid device entry")
        device = parse_device(item, timetables.get(str(item["id"])), shows, now)
        devices[device.id] = device
    return devices
