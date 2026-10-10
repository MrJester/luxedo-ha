"""Async, read-only client for the Luxedo portal's GPQ protocol.

The caller owns the aiohttp session and must supply an isolated CookieJar.
Only the observed read methods and login are allowed. No device-control RPCs.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData

from .const import BASE_URL

READ_METHODS = frozenset(
    {
        "login_login",
        "account_fetch_startup_data",
        "account_fetch_device_timetables",
        "device_bundle_down",
        "project_bundle_down",
        "lightshow_bundle_down",
    }
)


class LuxedoError(Exception):
    """Safe, non-sensitive error suitable for HA logs."""


class LuxedoAuthError(LuxedoError):
    """Login/session rejected."""


class LuxedoConnectionError(LuxedoError):
    """The portal could not be reached."""


class LuxedoProtocolError(LuxedoError):
    """The undocumented API changed or returned invalid data."""


class LuxedoRateLimitError(LuxedoError):
    """The server requested backoff."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__("Luxedo rate limit reached")
        self.retry_after = retry_after


class LuxedoClient:
    """Serialize requests and recover an expired session once per read."""

    def __init__(self, session: ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._csrf = ""
        self._rpc_session = str(uuid4())
        self._functions: dict[str, list[dict[str, Any]]] = {}
        self._authenticated = False
        self._lock = asyncio.Lock()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self._session.request(
                method,
                BASE_URL + path,
                headers={
                    "X-CSRFToken": self._csrf,
                    "Origin": BASE_URL,
                    "Referer": BASE_URL + "/",
                },
                timeout=ClientTimeout(total=30),
                allow_redirects=False,
                **kwargs,
            ) as response:
                if response.status in (401, 403):
                    raise LuxedoAuthError("Luxedo authentication rejected")
                if response.status == 429:
                    try:
                        delay = max(60, int(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        delay = 60
                    raise LuxedoRateLimitError(delay)
                if response.status >= 500:
                    raise LuxedoConnectionError("Luxedo service unavailable")
                if response.status != 200:
                    raise LuxedoProtocolError(
                        f"Unexpected Luxedo HTTP status {response.status}"
                    )
                try:
                    return await response.json()
                except (ValueError, ClientError) as err:
                    raise LuxedoProtocolError("Invalid Luxedo JSON response") from err
        except (ClientError, TimeoutError) as err:
            raise LuxedoConnectionError("Cannot connect to Luxedo") from err

    async def _send(self, fields: dict[str, str]) -> Any:
        # Browser FormData uses multipart, including for string-only requests.
        data = FormData(default_to_multipart=True)
        for key, value in {
            "_gpqsessionid": self._rpc_session,
            "_gpqforeigntype": "js",
            "_gpqcustom": "%7B%7D",
            **fields,
        }.items():
            data.add_field(key, value)
        return await self._request("POST", "/gpq", data=data)

    async def _call(self, name: str, *args: Any) -> Any:
        if name not in READ_METHODS:
            raise LuxedoProtocolError("RPC is outside the read-only scope")
        parameters = self._functions.get(name)
        if parameters is None or len(parameters) != len(args):
            raise LuxedoProtocolError(f"Unsupported Luxedo RPC signature: {name}")
        fields = {"_query": "query", "_fname": name}
        for parameter, value in zip(parameters, args, strict=True):
            kind = parameter.get("valtype")
            if isinstance(kind, list):
                kind = kind[0] if kind else None
            if kind == "json":
                value = quote(json.dumps(value, separators=(",", ":")), safe="~()*!.'-")
            fields[parameter["name"]] = str(value)
        return await self._send(fields)

    async def _login(self) -> None:
        self._authenticated = False
        self._session.cookie_jar.clear()
        self._rpc_session = str(uuid4())
        csrf = await self._request("GET", "/csrf_token")
        if not isinstance(csrf, dict) or not isinstance(csrf.get("csrfToken"), str):
            raise LuxedoProtocolError("Missing CSRF token")
        self._csrf = csrf["csrfToken"]
        registry = await self._send({"_query": "get_functions"})
        try:
            self._functions = {item["fname"]: item["args"] for item in registry}
            for parameters in self._functions.values():
                if not isinstance(parameters, list) or any(
                    not isinstance(p, dict) or not isinstance(p.get("name"), str)
                    for p in parameters
                ):
                    raise ValueError
        except (KeyError, TypeError, ValueError) as err:
            raise LuxedoProtocolError("Invalid RPC registry") from err
        await self._call("login_login", self._email, self._password, "")
        self._authenticated = True

    async def read(self, name: str, *args: Any) -> Any:
        """Read with one bounded relogin; persistent rejection triggers HA reauth."""
        if name == "login_login" or name not in READ_METHODS:
            raise LuxedoProtocolError("Not a read method")
        async with self._lock:
            had_session = self._authenticated
            if not had_session:
                await self._login()
            try:
                return await self._call(name, *args)
            except LuxedoAuthError:
                self._authenticated = False
                if not had_session:
                    raise
                await self._login()
                try:
                    return await self._call(name, *args)
                except LuxedoAuthError:
                    self._authenticated = False
                    raise

    async def startup(self) -> dict[str, Any]:
        """Retrieve account data and validate the stable account identity."""
        data = await self.read("account_fetch_startup_data")
        account_id(data)
        if not isinstance(data.get("device"), dict):
            raise LuxedoProtocolError("Missing device collection")
        return data


def account_id(data: Any) -> str:
    """Extract the account ID without exposing personal information."""
    try:
        users = list(data["user"].values())
        if len(users) != 1 or users[0]["id"] is None:
            raise ValueError
        return str(users[0]["id"])
    except (KeyError, AttributeError, TypeError, ValueError) as err:
        raise LuxedoProtocolError("Missing account identity") from err
