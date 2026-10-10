"""Read-only Luxedo integration."""

from __future__ import annotations

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import LuxedoClient
from .coordinator import LuxedoCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.CALENDAR]
type LuxedoConfigEntry = ConfigEntry[LuxedoCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LuxedoConfigEntry) -> bool:
    """Create an isolated HA-managed session for this account."""
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    client = LuxedoClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = LuxedoCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        session.detach()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxedoConfigEntry) -> bool:
    """Unload entities, listeners and the account's session."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
