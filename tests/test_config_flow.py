"""Real HA flow tests: setup, duplicate accounts, errors and reauthentication."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.luxedo.api import (
    LuxedoAuthError,
    LuxedoConnectionError,
    LuxedoProtocolError,
    LuxedoRateLimitError,
)

DATA = {"email": "owner@example.test", "password": "password-secret"}


async def test_user_flow(hass, startup):
    with (
        patch("custom_components.luxedo.config_flow.LuxedoClient") as api,
        patch("custom_components.luxedo.async_setup_entry", return_value=True),
    ):
        api.return_value.startup = AsyncMock(return_value=startup)
        result = await hass.config_entries.flow.async_init(
            "luxedo", context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == "42"
        assert result["data"] == DATA


async def test_duplicate(hass, startup):
    MockConfigEntry(domain="luxedo", unique_id="42", data=DATA).add_to_hass(hass)
    with patch("custom_components.luxedo.config_flow.LuxedoClient") as api:
        api.return_value.startup = AsyncMock(return_value=startup)
        result = await hass.config_entries.flow.async_init(
            "luxedo", context={"source": config_entries.SOURCE_USER}, data=DATA
        )
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LuxedoAuthError(), "invalid_auth"),
        (LuxedoConnectionError(), "cannot_connect"),
        (LuxedoProtocolError(), "unsupported_response"),
        (LuxedoRateLimitError(), "rate_limited"),
    ],
)
async def test_errors(hass, error, expected):
    with patch("custom_components.luxedo.config_flow.LuxedoClient") as api:
        api.return_value.startup = AsyncMock(side_effect=error)
        result = await hass.config_entries.flow.async_init(
            "luxedo", context={"source": config_entries.SOURCE_USER}, data=DATA
        )
    assert result["errors"] == {"base": expected}


@pytest.mark.parametrize("wrong_account", [False, True])
async def test_reauth(hass, startup, wrong_account):
    entry = MockConfigEntry(domain="luxedo", unique_id="42", data=DATA)
    entry.add_to_hass(hass)
    if wrong_account:
        startup["user"]["42"]["id"] = 99
    with (
        patch("custom_components.luxedo.config_flow.LuxedoClient") as api,
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        api.return_value.startup = AsyncMock(return_value=startup)
        result = await hass.config_entries.flow.async_init(
            "luxedo",
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**DATA, "password": "new-secret"}
        )
        assert result["reason"] == (
            "wrong_account" if wrong_account else "reauth_successful"
        )
        assert entry.data["password"] == (
            "password-secret" if wrong_account else "new-secret"
        )
