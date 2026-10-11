# Luxedo for Home Assistant

Read-only Home Assistant integration for projector status and schedules from
<https://luxedo.app/>. Uses native HA config entries, UI setup and reauthentication,
a HA-managed HTTP session with an isolated cookie jar, `DataUpdateCoordinator`,
device/entity registries, and native calendar entities.

**Status: initial implementation, awaiting authenticated hardware validation.**
The public portal's CSRF bootstrap and RPC registry have been verified. The device
and schedule models were derived from its frontend. Automated tests use synthetic
fixtures; a successful test run does not prove compatibility with your account,
projector model, firmware, or the server's session-expiration behavior.

Requires Home Assistant **2026.2 or later**. Local tests use HA 2026.2.3.

## Installation

Install through HACS without SSH or manually copying files:

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/MrJester/luxedo-ha` and select **Integration**.
3. Find **Luxedo** in HACS and download it.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → Luxedo** and enter
   your luxedo.app email and password.

[Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=MrJester&repository=luxedo-ha&category=integration)

HACS handles subsequent updates. This is a custom repository, not a listing in the
HACS default catalog. For manual installation, copy `custom_components/luxedo`
into your HA configuration's `custom_components` directory and restart HA.

This is an unofficial community integration, not affiliated with Luxedo.

## Entities

Each portal device receives:

| Entity | Behavior |
| --- | --- |
| Connectivity | Portal-reported online/offline for Luxedo/LuxCast RPi devices; unknown for unsupported models/states |
| Status | Raw reported status, such as `IDLE`, `PROJECT`, `PROJ_TT`, or `LOST` |
| Current show | Show name when playback is reported; unknown if idle or unreported |
| Next show | Earliest future scheduled event name |
| Next show start | Timestamp of that event |
| Schedule | Read-only calendar, including recurring and overnight events |
| Firmware | Diagnostic sensor, disabled by default; also available in device info |

Status refreshes every 60 seconds; the account/show catalog and schedules every
five minutes. Devices added to the account are discovered on later updates.
Removed devices become unavailable. A cloud failure makes entities unavailable;
it does not report the projector as off. Transient errors back off to at most
16-minute polling, and successful updates restore normal polling. HTTP 429
responses honor numeric Retry-After values (otherwise at least 60 seconds).

Next-show sensors report scheduled events, not guaranteed playback. Overlapping
events remain visible; priority is included in calendar descriptions. The
integration does not emulate projector priority arbitration, overrides, download
readiness, or runtime playback. The calendar's current event is the earliest
starting active event, otherwise the next event.

Schedules preserve the portal's timestamps and RRULE timezone semantics. UTC rules
stay UTC across DST. Explicit TZID rules use that timezone. Recurrence dates without a
timezone marker are interpreted as UTC, matching the Luxedo portal. One-time
timestamps without a timezone remain unsupported.
Missing timetables are unavailable; an explicit empty timetable is an empty
calendar. An unsupported event makes that device's schedule entities unavailable
while status continues working. Diagnostics report the failing event index, field, reason, and format flags. Expansion is
performed outside HA's event loop and capped at 10,000 occurrences per schedule
per query. Secondly recurrences and calendar-month/year durations are unsupported.

## Authentication and privacy

HA stores the email/password in the config entry so the client can log in after a
restart or session expiration. This is HA's normal configuration storage, not a
separate encrypted credential vault. Cookies and CSRF tokens are kept in memory
in a per-account cookie jar. No browser, exported cookie file, external credential
store, OAuth registration, or YAML credentials are needed.

The client retries an expired session once. Persistent authentication rejection
uses HA's built-in reauthentication flow; the replacement credentials must resolve
to the same account ID. Network outages do not request new credentials. The client
never logs credentials, tokens, raw response bodies, or account payloads.
Diagnostics export only an allowlist of non-personal status/version/count fields.

Only login and documented-in-this-repository read RPCs are allowlisted. This
version cannot change power, start/stop shows, claim device control, edit schedules,
update firmware, or upload media.

## Development

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check custom_components tests
uv run ruff format --check custom_components tests
```

Tests cover HTTP serialization, auth renewal/rejection, config flows and reauth,
HA entity setup/unload, discovery, availability, schedule polling cadence,
calendar boundaries, UTC/TZID recurrence across DST, and sanitized diagnostics.

See [protocol notes](docs/protocol.md) for observations and remaining unknowns,
and [device validation](docs/device-validation.md) for the first installation run.
