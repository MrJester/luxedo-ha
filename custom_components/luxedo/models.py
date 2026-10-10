"""Validated device and schedule models, independent of Home Assistant."""

from __future__ import annotations

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


def parse_schedules(raw: Any, shows: dict[str, str]) -> tuple[Schedule, ...] | None:
    """Null/missing timetable is unknown; an explicit empty list is empty."""
    if raw is None:
        return None
    try:
        events = raw["events"]
        if not isinstance(events, list):
            raise ValueError
        result = []
        for event in events:
            timing = event["timing"]
            show_id = str(event["project_id"])
            common = dict(
                uid=str(event["id"]),
                summary=event.get("name") or shows.get(show_id, "Luxedo show"),
                show_id=show_id,
                priority=event.get("priority"),
            )
            repeat = event.get("repeat", 0)
            if repeat not in (0, 1, False, True):
                raise ValueError
            if repeat:
                rule_text = timing["rrule_string"]
                if "DTSTART" not in rule_text or "FREQ=SECONDLY" in rule_text:
                    raise ValueError
                rule = rrulestr(rule_text, tzids=ZoneInfo)
                first = next(iter(rule), None)
                if first is not None and first.tzinfo is None:
                    raise ValueError
                duration = parse_duration(timing["duration_iso"])
                if not isinstance(duration, timedelta) or duration <= timedelta():
                    raise ValueError
                result.append(Schedule(**common, rule=rule_text, duration=duration))
            else:
                start, end = _date(timing["t_start"]), _date(timing["t_end"])
                if end <= start:
                    raise ValueError
                result.append(Schedule(**common, start=start, end=end))
        return tuple(result)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as err:
        raise LuxedoProtocolError("Unsupported Luxedo timetable format") from err


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
        except LuxedoProtocolError:
            schedules, upcoming, calendar, schedule_error = None, [], [], True
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
