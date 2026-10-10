"""Exercise the real HTTP client with mocked responses and multipart inspection."""

from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession, CookieJar
from aioresponses import aioresponses

from custom_components.luxedo.api import (
    LuxedoAuthError,
    LuxedoClient,
    LuxedoConnectionError,
    LuxedoProtocolError,
    LuxedoRateLimitError,
)
from custom_components.luxedo.const import BASE_URL

REGISTRY = [
    {
        "fname": "login_login",
        "args": [
            {"name": n, "valtype": "string"}
            for n in ["email", "password", "desired_next_url"]
        ],
    },
    {"fname": "account_fetch_startup_data", "args": []},
    {
        "fname": "device_bundle_down",
        "args": [{"name": "instance_ids", "valtype": "json"}],
    },
]


def login_responses(mock):
    mock.get(BASE_URL + "/csrf_token", payload={"csrfToken": "csrf-secret"})
    mock.post(BASE_URL + "/gpq", payload=REGISTRY)
    mock.post(BASE_URL + "/gpq", payload={})


async def test_login_and_wire_format(startup):
    async with ClientSession(cookie_jar=CookieJar()) as session:
        client = LuxedoClient(session, "owner@example.test", "password-secret")
        with aioresponses() as mock:
            login_responses(mock)
            mock.post(BASE_URL + "/gpq", payload=startup)
            assert await client.startup() == startup
            mock.post(BASE_URL + "/gpq", payload={})
            await client.read("device_bundle_down", [7, 8])
            calls = [
                call
                for (method, _), values in mock.requests.items()
                if method == "POST"
                for call in values
            ]
            fields = {
                field[0]["name"]: field[2] for field in calls[-1].kwargs["data"]._fields
            }
            assert fields["instance_ids"] == "%5B7%2C8%5D"
            assert fields["_fname"] == "device_bundle_down"
            assert calls[-1].kwargs["data"].is_multipart
            assert calls[-1].kwargs["headers"]["X-CSRFToken"] == "csrf-secret"


async def test_expired_session_recovers_once(startup):
    async with ClientSession() as session:
        client = LuxedoClient(session, "email", "password")
        with aioresponses() as mock:
            login_responses(mock)
            mock.post(BASE_URL + "/gpq", payload=startup)
            await client.startup()
            mock.post(BASE_URL + "/gpq", status=403)
            login_responses(mock)
            mock.post(BASE_URL + "/gpq", payload=startup)
            assert await client.startup() == startup
            mock.post(BASE_URL + "/gpq", status=403)
            login_responses(mock)
            mock.post(BASE_URL + "/gpq", status=403)
            with pytest.raises(LuxedoAuthError):
                await client.startup()


async def test_login_rejection_not_retried():
    async with ClientSession() as session:
        client = LuxedoClient(session, "email", "password")
        with aioresponses() as mock:
            mock.get(BASE_URL + "/csrf_token", payload={"csrfToken": "token"})
            mock.post(BASE_URL + "/gpq", payload=REGISTRY)
            mock.post(BASE_URL + "/gpq", status=403)
            with pytest.raises(LuxedoAuthError):
                await client.startup()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, LuxedoRateLimitError),
        (503, LuxedoConnectionError),
        (302, LuxedoProtocolError),
        (499, LuxedoProtocolError),
    ],
)
async def test_failure_classification(status, error):
    async with ClientSession() as session:
        client = LuxedoClient(session, "email", "password")
        with aioresponses() as mock:
            mock.get(BASE_URL + "/csrf_token", status=status)
            with pytest.raises(error):
                await client.startup()


async def test_timeout():
    async with ClientSession() as session:
        client = LuxedoClient(session, "email", "password")
        with aioresponses() as mock:
            mock.get(BASE_URL + "/csrf_token", exception=TimeoutError())
            with pytest.raises(LuxedoConnectionError):
                await client.startup()


async def test_only_read_calls_allowed():
    async with ClientSession() as session:
        client = LuxedoClient(session, "email", "password")
        client._request = AsyncMock()
        with pytest.raises(LuxedoProtocolError):
            await client.read("devops_set_projector_power", 7, True)
        client._request.assert_not_called()
