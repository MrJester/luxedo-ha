"""Load actual HA platforms and test availability, discovery and cleanup."""

from copy import deepcopy
from datetime import datetime

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luxedo.api import LuxedoAuthError, LuxedoConnectionError
from custom_components.luxedo.calendar import LuxedoCalendar
from custom_components.luxedo.const import UPDATE_INTERVAL
from custom_components.luxedo.diagnostics import async_get_config_entry_diagnostics


async def setup(hass):
    entry = MockConfigEntry(
        domain="luxedo",
        unique_id="42",
        title="Luxedo",
        data={"email": "owner@example.test", "password": "secret"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_calendar_diagnostics_unload(hass, client, freezer):
    freezer.move_to("2026-10-10T20:00:00Z")
    entry = await setup(hass)
    states = {s.entity_id: s for s in hass.states.async_all()}
    assert states["binary_sensor.porch_connectivity"].state == "on"
    assert states["sensor.porch_status"].state == "PROJECT"
    assert states["sensor.porch_current_show"].state == "Halloween"
    assert states["sensor.porch_next_show"].state == "Evening show"
    assert states["calendar.porch_schedule"].state == "off"
    calendar = LuxedoCalendar(entry.runtime_data, "7")
    events = await calendar.async_get_events(
        hass,
        datetime.fromisoformat("2026-10-10T00:00:00Z"),
        datetime.fromisoformat("2026-10-12T00:00:00Z"),
    )
    assert len(events) == 1
    assert events[0].summary == "Evening show"
    assert calendar.supported_features == 0
    diagnostic = str(await async_get_config_entry_diagnostics(hass, entry))
    for secret in ("secret", "owner@example", "Porch", "Halloween", "Evening show"):
        assert secret not in diagnostic
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_cloud_failure_is_unavailable_not_off(hass, client):
    entry = await setup(hass)
    client.read.side_effect = LuxedoConnectionError("Cannot connect")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.porch_connectivity").state == "unavailable"
    assert entry.runtime_data.update_interval == UPDATE_INTERVAL * 2


async def test_offline_and_recovery(hass, client, startup):
    entry = await setup(hass)
    startup["device"]["7"]["eidos"]["status"] = "LOST"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.porch_connectivity").state == "off"
    assert hass.states.get("sensor.porch_status").state == "LOST"
    startup["device"]["7"]["eidos"]["status"] = "IDLE"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.porch_connectivity").state == "on"


async def test_dynamic_devices_and_removal(hass, client, startup):
    entry = await setup(hass)
    extra = deepcopy(startup["device"]["7"])
    extra.update(id=8, name="Garage")
    startup["device"]["8"] = extra
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.garage_status").state == "PROJECT"
    del startup["device"]["7"]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.porch_status").state == "unavailable"


async def test_auth_failure(hass, client):
    entry = await setup(hass)
    client.read.side_effect = LuxedoAuthError()
    with pytest.raises(ConfigEntryAuthFailed):
        await entry.runtime_data._async_update_data()


async def test_startup_network_retry(hass, client):
    client.startup.side_effect = LuxedoConnectionError("Cannot connect")
    entry = MockConfigEntry(
        domain="luxedo",
        unique_id="42",
        title="Luxedo",
        data={"email": "email", "password": "secret"},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_schedule_cadence(hass, client, freezer):
    freezer.move_to("2026-10-10T20:00:00Z")
    entry = await setup(hass)
    assert client.startup.call_count == 1
    freezer.move_to("2026-10-10T20:01:00Z")
    await entry.runtime_data.async_refresh()
    assert client.startup.call_count == 1
    freezer.move_to("2026-10-10T20:05:00Z")
    await entry.runtime_data.async_refresh()
    assert client.startup.call_count == 2


async def test_invalid_schedule_preserves_status(hass, client, timetables):
    timetables["7"]["events"] = "bad"
    await setup(hass)
    assert hass.states.get("sensor.porch_status").state == "PROJECT"
    assert hass.states.get("calendar.porch_schedule").state == "unavailable"
    assert hass.states.get("sensor.porch_next_show").state == "unavailable"


async def test_unmarked_recurring_dates_populate_schedule_entities(
    hass, client, freezer, timetables
):
    freezer.move_to("2026-10-11T20:00:00Z")
    timetables["7"]["events"] = [
        {
            "id": "recurring-event",
            "project_id": 9,
            "name": "Evening show",
            "repeat": 1,
            "priority": 0,
            "timing": {
                "rrule_string": (
                    "DTSTART:20261011T230000\nRRULE:FREQ=DAILY;UNTIL=20261013T230000"
                ),
                "duration_iso": "PT2H30M",
            },
        }
    ]
    entry = await setup(hass)
    assert hass.states.get("sensor.porch_next_show").state == "Evening show"
    assert (
        hass.states.get("sensor.porch_next_show_start").state
        == "2026-10-11T23:00:00+00:00"
    )
    assert hass.states.get("calendar.porch_schedule").state == "off"
    calendar = LuxedoCalendar(entry.runtime_data, "7")
    events = await calendar.async_get_events(
        hass,
        datetime.fromisoformat("2026-10-11T00:00:00Z"),
        datetime.fromisoformat("2026-10-14T00:00:00Z"),
    )
    assert len(events) == 3
    assert events[0].start == datetime.fromisoformat("2026-10-11T23:00:00Z")
    assert events[0].end == datetime.fromisoformat("2026-10-12T01:30:00Z")
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["devices"][0]["schedule_available"] is True
    assert diagnostics["devices"][0]["schedule_parse_error"] is False
    assert diagnostics["devices"][0]["schedule_error_details"] is None
