## v0.1.1 — Schedule parsing diagnostics

The first real-device report confirms that authentication and cloud updates work,
but a returned timetable is rejected by the schedule parser. Version 0.1.0 only
reported a boolean error, so it did not identify the incompatible field.

This update adds `schedule_error_details` to the integration's downloadable
diagnostics. It reports the failing event index, field, reason, and value-format
flags while excluding credentials, show names, identifiers, and actual timestamps.

After updating through HACS and restarting Home Assistant, download fresh Luxedo
diagnostics if schedule entities remain unavailable. These details are needed to
identify and fix the affected timetable format; this release does not claim to
resolve the underlying schedule incompatibility.
