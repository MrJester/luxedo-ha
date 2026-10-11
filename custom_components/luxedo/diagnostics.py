"""Allowlisted diagnostics: never export account data, cookies or raw payloads."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "integration_version": "0.1.2",
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": coordinator.update_interval.total_seconds(),
        "devices": [
            {
                "model": device.model,
                "firmware": device.firmware,
                "status": device.status,
                "online": device.online,
                "schedule_available": device.schedules is not None,
                "schedule_parse_error": device.schedule_error,
                "schedule_error_details": device.schedule_error_details,
                "schedule_count": len(device.schedules)
                if device.schedules is not None
                else None,
            }
            for device in coordinator.data.values()
        ],
    }
