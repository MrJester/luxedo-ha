## v0.1.2 — Fix recurring schedules reported as unavailable

Luxedo can return recurrence dates without a trailing timezone marker. Earlier
versions rejected these rules, making the calendar and upcoming-show sensors
unavailable even when shows were scheduled.

The parser now matches the Luxedo portal: DTSTART and UNTIL values without a
TZID are interpreted as UTC. Explicit timezone rules retain their existing
behavior. No Home Assistant timezone setting change is needed.

Regression tests reproduce the rejected format and verify next-show sensors,
calendar events, inclusive recurrence end dates, and daylight-saving behavior.

Update Luxedo through HACS and restart Home Assistant. The reported
`rrule_string / missing_timezone` failure is addressed by this release; confirm
that upcoming-show times match your portal after updating.
