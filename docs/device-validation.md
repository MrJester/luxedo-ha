# First device validation

The implementation has not logged into a real Luxedo account or changed a device.

1. Install the integration and enter credentials in HA's native setup dialog.
   Verify one device entry per portal device and no duplicate entities after reload.
2. Compare Status, Connectivity and Current show with the portal while the projector
   is idle, playing an existing show, and offline. Allow 60 seconds for updates.
3. Compare a one-time schedule and a recurring schedule with the HA calendar,
   including one crossing midnight. Allow five minutes for portal schedule changes.
   Verify calendar timestamps in your HA timezone and around the next DST boundary.
4. Restart HA. Verify automatic login, stable IDs and restored updates.
5. Reload/unload the integration. Verify no continuing polling after unload.
6. Leave it running while using the portal normally. Confirm portal use does not
   invalidate HA sessions (or vice versa). Continue through an actual session expiry.
7. If credentials change, verify HA prompts for reauthentication and resumes updates
   with the same account. Do not paste passwords, cookies or raw HAR files into issues.
8. If a schedule is unavailable while status works, download integration diagnostics
   and inspect `schedule_parse_error` and `schedule_error_details`. The latter
   identifies the failing field, reason, and value types without including show
   names, identifiers, dates, credentials, or raw server values.

Acceptance: status and schedules match the portal, restart/session recovery works,
cloud outages are distinct from offline projector status, and a multiday run does
not produce persistent errors or disturb portal/device operation.
