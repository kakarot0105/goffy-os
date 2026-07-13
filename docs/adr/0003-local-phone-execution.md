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
- Require the plan to declare PHONE, the exact allowlisted tool name, and SAFE
  permission before reading device state.
- Validate battery percentage before emitting a result, then emit a separate
  verification event before the task can become successful.
- Run the framework read off the UI dispatcher with a bounded timeout.
- Do not register a receiver, poll, request a permission, or start background work.

## Consequences

The first PHONE command works without a Hub or network and reuses the same
observable timeline as MAC execution. Android framework access remains behind a
small injectable source for JVM tests. Real battery values, responsiveness, and
OEM behavior still require Moto G verification.
