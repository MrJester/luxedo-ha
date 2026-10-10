# Luxedo protocol observations

Inspected 2026-10-10. Public portal bundle:
https://luxedo.app/assets/index-CWLzf7Dt.js

No account credentials were used in discovery. GET /csrf_token followed by the
public get_functions RPC was successfully exercised. All other live responses
remain unverified. Frontend source is evidence of intended wire behavior, not a
stable vendor API contract.

## GPQ transport

1. GET `/csrf_token`, preserving cookies; JSON contains `csrfToken`.
2. POST multipart FormData to `/gpq` with `X-CSRFToken`, cookies, Origin, Referer.
3. Common fields: `_gpqsessionid` (client-generated UUID), `_gpqforeigntype=js`,
   `_gpqcustom=%7B%7D` (URI-encoded empty JSON object).
4. `_query=get_functions` returns a list of `{fname, args}`. Each argument has
   `name`, `valtype`, and `required` metadata. Argument names are discovered at
   runtime, not inferred from JavaScript parameter names.
5. A call uses `_query=query`, `_fname=<name>`, and named argument form fields.
   JSON arguments are compact JSON followed by JavaScript-compatible URI encoding.
   The frontend's namespace wrappers do not prefix RPC names on the wire.
6. Successful responses are direct JSON results, without an assumed envelope.

Verified public signatures:

| RPC | Arguments |
| --- | --- |
| login_login | email:string, password:string, desired_next_url:string |
| account_fetch_startup_data | none |
| account_fetch_device_timetables | none |
| device_bundle_down | instance_ids:json |
| project_bundle_down | instance_ids:json |
| lightshow_bundle_down | instance_ids:json |

The integration sends an empty desired_next_url and requests all devices with
instance_ids = []. It does not expose a generic RPC service.

## Data models observed in frontend

`account_fetch_startup_data` is consumed as `user`, `device`, `scene`, `lightshow`,
and other ID-keyed collections. Device fields used here: `id`, `name`, `type_id`,
`version_crnt`, `status`, `eidos.status`, `eidos.proj_id`, `eidos.player.id`.
Sensitive fields such as device `password` exist and must never enter diagnostics.

For RPi devices (`dev_luxedo`, `dev_luxcast`), the portal's online getter recognizes
IDLE, PROJECT, PROJ_TT and PNC. The integration treats OFF, LOST and NEW as offline
and leaves other states unknown rather than inferring power state. Device-group
and browser-projector connectivity semantics have not been validated.

`account_fetch_device_timetables` maps device IDs to timetable objects:

- `metadata.last_modified`, `version`, `events`.
- Event fields: `id`, `name`, `project_id`, `priority`, `repeat`.
- One-time timing: `t_start`, `t_end` (ISO datetimes).
- Repeating timing: `rrule_string`, `duration_iso`.

The frontend constructs UTC DTSTART/UNTIL recurrence rules when saving through
its scheduler; this implementation preserves that rule rather than inventing
wall-clock DST adjustments.

## Deliberate transport choice

The portal also sends `_query=poll_standard`, `_gpqpolln` and dispatches callbacks
such as `device_on_status_change(device_id, eidos)`. This first version periodically
reads device bundles instead of reproducing the stateful callback stream. Confirm
on hardware that bundle reads return fresh eidos; if they are stale, implement and
test the observed polling callback protocol before claiming live-status support.

The device-side `timetable_get_frontend` method exists behind `plato_call`, but the
frontend may acquire control after certain failures. This integration exclusively
uses the account-level read method and never acquires control.

## Remaining live validation

- Login error statuses/body behavior; frontend catches all login errors generically.
- Actual cookie name/domain/expiry, CSRF rotation, and concurrent portal sessions.
- Account identity and collection shapes across subscription/model variants.
- Whether bundle reads include current status and playback for each firmware.
- Null/absent schedules and inherited/group schedule behavior.
- Actual recurrence timestamps, DST behavior, priority and temporary overrides.
- Rate limits and appropriate status refresh interval.

HTTP 401/403 trigger bounded relogin and then HA reauth. Other unexpected 4xx
responses are protocol errors, not assumed bad passwords. HTML/redirect responses
are rejected rather than silently parsed or followed. TLS verification is enabled.
