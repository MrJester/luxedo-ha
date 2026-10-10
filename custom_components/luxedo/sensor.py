"""Status, playback and next scheduled show sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory

from .entity import LuxedoEntity, discover_entities

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(key="status", translation_key="status"),
    SensorEntityDescription(key="current_show", translation_key="current_show"),
    SensorEntityDescription(key="next_show", translation_key="next_show"),
    SensorEntityDescription(
        key="next_start",
        translation_key="next_start",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    discover_entities(
        entry,
        async_add_entities,
        lambda coordinator, id_: [
            LuxedoSensor(coordinator, id_, description) for description in DESCRIPTIONS
        ],
    )


class LuxedoSensor(LuxedoEntity, SensorEntity):
    def __init__(self, coordinator, device_id, description) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and (
            self.entity_description.key not in ("next_show", "next_start")
            or self.device.schedules is not None
        )

    @property
    def native_value(self):
        if not self.available:
            return None
        key = self.entity_description.key
        if key == "next_show":
            return self.device.next_show.summary if self.device.next_show else None
        if key == "next_start":
            return self.device.next_show.start if self.device.next_show else None
        return getattr(self.device, key)
