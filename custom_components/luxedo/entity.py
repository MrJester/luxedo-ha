"""Shared device identity and dynamic entity discovery."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN
from .coordinator import LuxedoCoordinator
from .models import Device


class LuxedoEntity(CoordinatorEntity[LuxedoCoordinator]):
    """An entity attached to a Luxedo device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: LuxedoCoordinator, device_id: str, key: str
    ) -> None:
        super().__init__(coordinator, context=device_id)
        self.device_id = device_id
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{device_id}_{key}"

    @property
    def device(self) -> Device:
        return self.coordinator.data[self.device_id]

    @property
    def available(self) -> bool:
        return super().available and self.device_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.name,
            manufacturer="Luxedo",
            model=device.model,
            sw_version=device.firmware,
            configuration_url=BASE_URL,
        )


@callback
def discover_entities(entry, async_add_entities, factory: Callable) -> None:
    """Add newly registered devices without a restart; missing ones go unavailable."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def discover() -> None:
        new = set(coordinator.data) - known
        if new:
            known.update(new)
            async_add_entities(
                [
                    entity
                    for device_id in sorted(new)
                    for entity in factory(coordinator, device_id)
                ]
            )

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
