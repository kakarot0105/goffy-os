# ADR 0002: Android invocation client

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY OS needs one narrow Android-to-Hub action that is deterministic,
inspectable, and safe enough to exercise the transport boundary without
introducing pairing, broad routing, or mutable Mac authority.

## Decision

- Route only the exact `Show/Check [me] my Mac status` command family to
  `SAFE mac.system_info`.
- Open a fresh authenticated WebSocket for each invocation and send the bearer
  token only in the `Authorization` header.
- Use a strict Kotlin codec and task reducer that reject unsupported fields,
  mismatched correlation IDs, unexpected execution targets, invalid ordering,
  and oversized messages.
- Treat `ToolResult` as structured data and `VerificationResult` as the success
  boundary.
- Retry only connection failures that happen before the invocation is sent,
  capped at 2 retries and 3 total attempts. Do not replay after send.
- Let cancel stop only the local Android job and socket. Do not claim Hub-side
  completion or termination.
- Require `wss://.../ws/v1` for release endpoints. Allow debug cleartext only
  for `localhost` and `127.0.0.1` through Android network security config and
  the USB `adb reverse` flow.

## Consequences

The slice is predictable and testable for one SAFE read-only action, but it is
not a pairing flow, not approved for LAN use, and not ready for mutating tools.
The shared fixture `protocol/fixtures/mac-system-info-flow.jsonl` must stay
compatible across Android and Python tests. Physical Moto G verification remains
open.
