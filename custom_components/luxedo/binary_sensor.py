"""Reported projector connectivity, independent of cloud availability."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import LuxedoEntity, discover_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    discover_entities(
        entry,
        async_add_entities,
        lambda coordinator, id_: [LuxedoConnectivity(coordinator, id_)],
    )


class LuxedoConnectivity(LuxedoEntity, BinarySensorEntity):
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "connectivity")

    @property
    def is_on(self) -> bool | None:
        return self.device.online if self.available else None
