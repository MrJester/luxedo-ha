"""Synthetic fixtures matching the observed portal schemas; no account secrets."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

STARTUP = {
    "user": {"42": {"id": 42, "email": "owner@example.test"}},
    "device": {
        "7": {
            "id": 7,
            "name": "Porch",
            "type_id": "dev_luxedo",
            "version_crnt": "3.11.0",
            "password": "device-secret",
            "eidos": {"status": "PROJECT", "player": {"id": 9}},
        }
    },
    "scene": {"9": {"id": 9, "name": "Halloween"}},
    "lightshow": {},
}
TIMETABLES = {
    "7": {
        "version": 1,
        "metadata": {"last_modified": "2026-10-10T00:00:00Z"},
        "events": [
            {
                "id": "event-1",
                "name": "Evening show",
                "project_id": 9,
                "priority": 0,
                "repeat": 0,
                "timing": {
                    "t_start": "2026-10-10T23:00:00Z",
                    "t_end": "2026-10-11T01:00:00Z",
                },
            }
        ],
    }
}


@pytest.fixture(autouse=True)
def enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def startup():
    return deepcopy(STARTUP)


@pytest.fixture
def timetables():
    return deepcopy(TIMETABLES)


@pytest.fixture
def client(startup, timetables):
    with patch("custom_components.luxedo.LuxedoClient", autospec=True) as mock:
        instance = mock.return_value
        instance.startup = AsyncMock(return_value=startup)

        async def read(name, *args):
            return (
                timetables
                if name == "account_fetch_device_timetables"
                else startup["device"]
            )

        instance.read = AsyncMock(side_effect=read)
        yield instance
