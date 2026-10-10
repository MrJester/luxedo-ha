"""Native Home Assistant configuration and reauthentication."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    LuxedoAuthError,
    LuxedoClient,
    LuxedoConnectionError,
    LuxedoProtocolError,
    LuxedoRateLimitError,
    account_id,
)
from .const import DOMAIN


class LuxedoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one entry per stable Luxedo account ID."""

    VERSION = 1

    async def _validate(self, data: dict[str, Any]) -> str:
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=CookieJar()
        )
        try:
            client = LuxedoClient(session, data[CONF_EMAIL], data[CONF_PASSWORD])
            return account_id(await client.startup())
        finally:
            session.detach()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return await self._credentials("user", user_input)

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        return await self._credentials("reauth_confirm", user_input)

    async def _credentials(self, step: str, user_input) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            user_input = {**user_input, CONF_EMAIL: user_input[CONF_EMAIL].strip()}
            try:
                identity = await self._validate(user_input)
            except LuxedoAuthError:
                errors["base"] = "invalid_auth"
            except LuxedoConnectionError:
                errors["base"] = "cannot_connect"
            except LuxedoRateLimitError:
                errors["base"] = "rate_limited"
            except LuxedoProtocolError:
                errors["base"] = "unsupported_response"
            else:
                await self.async_set_unique_id(identity)
                if step == "reauth_confirm":
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=user_input
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Luxedo", data=user_input)
        email = ""
        if step == "reauth_confirm":
            email = self._get_reauth_entry().data[CONF_EMAIL]
        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=email): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)
