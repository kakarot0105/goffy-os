# ADR 0003: Local phone execution boundary

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY OS must prefer deterministic PHONE execution for small private tasks, but
the first Android runtime modeled every event and result around the Mac Hub.
Adding phone tools directly to the ViewModel would duplicate authorization,
progress, verification, and error behavior.

## Decision

- Use one typed execution-event model for PHONE, MAC, and future CLOUD routes.
- Represent tool results with a sealed content type rather than untyped maps.
- Put phone capabilities behind a fixed `PhoneToolGateway`; do not expose a
  generic Android command or reflection interface.
- Implement `phone.battery.status` with one on-demand `BatteryManager` read.
- Implement `phone.device.info` with only manufacturer, user-visible model,
  Android release, SDK level from `Build`, and GOFFY home/system-app status;
  collect no stable identifier.
- Require the plan to declare PHONE, the exact allowlisted tool name, and SAFE
  permission before reading device state.
- Validate battery percentage before emitting a result, then emit a separate
  verification event before the task can become successful.
- Run the framework read off the UI dispatcher with a bounded timeout.
- Do not register a receiver, poll, request a permission, or start background work.

## Consequences

The first PHONE commands work without a Hub or network and reuse the same
observable timeline as MAC execution. Android framework access remains behind
small injectable sources for JVM tests. Device model is treated as local display
data, not an identity key; any future persistence or remote transmission requires
a separate data-policy decision. Real values, responsiveness, and OEM behavior
still require Moto G verification.

## References

- [Android `Build` API](https://developer.android.com/reference/android/os/Build)
- [Android `Build.VERSION` API](https://developer.android.com/reference/android/os/Build.VERSION)
- [Android identifier best practices](https://developer.android.com/identity/user-data-ids)
