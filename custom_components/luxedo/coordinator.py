"""Coordinate status and timetable reads using HA's update lifecycle."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    LuxedoAuthError,
    LuxedoClient,
    LuxedoError,
    LuxedoProtocolError,
    LuxedoRateLimitError,
    account_id,
)
from .const import DOMAIN, SCHEDULE_INTERVAL, UPDATE_INTERVAL
from .models import Device, build_devices

_LOGGER = logging.getLogger(__name__)


class LuxedoCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """One shared status poll and a slower schedule/catalog refresh."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: LuxedoClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._entry = entry
        self._timetables: dict[str, Any] = {}
        self._shows: dict[str, str] = {}
        self._last_catalog: datetime | None = None
        self._failures = 0

    async def _async_update_data(self) -> dict[str, Device]:
        now = dt_util.utcnow()
        try:
            if (
                self._last_catalog is None
                or now - self._last_catalog >= SCHEDULE_INTERVAL
            ):
                startup = await self.client.startup()
                if account_id(startup) != self._entry.unique_id:
                    raise LuxedoAuthError("Luxedo account identity changed")
                raw = startup["device"]
                shows = {}
                for key in ("scene", "lightshow"):
                    collection = startup.get(key, {})
                    if not isinstance(collection, dict):
                        raise LuxedoProtocolError("Invalid show collection")
                    for item in collection.values():
                        if not isinstance(item, dict) or "id" not in item:
                            raise LuxedoProtocolError("Invalid show entry")
                        shows[str(item["id"])] = item.get("name") or "Luxedo show"
                timetables = await self.client.read("account_fetch_device_timetables")
                data = await self.hass.async_add_executor_job(
                    build_devices, raw, timetables, shows, now
                )
                self._shows, self._timetables = shows, timetables
                self._last_catalog = now
            else:
                raw = await self.client.read("device_bundle_down", [])
                data = await self.hass.async_add_executor_job(
                    build_devices, raw, self._timetables, self._shows, now
                )
            self._failures = 0
            self.update_interval = UPDATE_INTERVAL
            return data
        except LuxedoAuthError as err:
            raise ConfigEntryAuthFailed(
                "Luxedo authentication needs attention"
            ) from err
        except LuxedoRateLimitError as err:
            raise UpdateFailed(
                "Luxedo rate limit reached", retry_after=err.retry_after
            ) from err
        except LuxedoError as err:
            self._failures = min(self._failures + 1, 4)
            self.update_interval = UPDATE_INTERVAL * (2**self._failures)
            raise UpdateFailed(str(err)) from err
