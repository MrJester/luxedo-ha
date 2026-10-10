"""Read-only projector calendars backed by Luxedo timetables."""

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .api import LuxedoProtocolError
from .entity import LuxedoEntity, discover_entities
from .models import Occurrence

PARALLEL_UPDATES = 0


def calendar_event(event: Occurrence) -> CalendarEvent:
    return CalendarEvent(
        start=event.start,
        end=event.end,
        summary=event.summary,
        uid=event.uid,
        description=f"Luxedo show {event.show_id}; priority {event.priority}",
    )


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    discover_entities(
        entry,
        async_add_entities,
        lambda coordinator, id_: [LuxedoCalendar(coordinator, id_)],
    )


class LuxedoCalendar(LuxedoEntity, CalendarEntity):
    _attr_translation_key = "schedule"
    _attr_supported_features = 0

    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "schedule")

    @property
    def available(self) -> bool:
        return super().available and self.device.schedules is not None

    @property
    def event(self) -> CalendarEvent | None:
        if self.available and self.device.calendar_event:
            return calendar_event(self.device.calendar_event)
        return None

    async def async_get_events(
        self, hass, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        if not self.available:
            raise HomeAssistantError("Luxedo schedule is unavailable")
        schedules = self.device.schedules
        start, end = dt_util.as_utc(start_date), dt_util.as_utc(end_date)

        def expand() -> list[CalendarEvent]:
            events = [
                event
                for schedule in schedules or ()
                for event in schedule.occurrences(start, end)
            ]
            return [
                calendar_event(event) for event in sorted(events, key=lambda e: e.start)
            ]

        try:
            return await hass.async_add_executor_job(expand)
        except LuxedoProtocolError as err:
            raise HomeAssistantError(str(err)) from err
