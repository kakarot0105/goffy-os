# ADR 0036: Foreground token rotation reminder

## Status

Accepted

## Context

GOFFY paired credentials can now rotate manually, but the phone did not show
when the current bearer was old enough to deserve operator attention. Adding
automatic rotation or scheduled background reminders would introduce new power,
audit, retry, and failure semantics before real-device process-failure validation
is complete.

The Android credential record also only tracked the original credential creation
time. After a manual rotation, that timestamp is intentionally preserved for
identity continuity, so it cannot be used as the current bearer age.

## Decision

- Add `tokenIssuedAt` to the encrypted Android paired credential record and bump
  the local record schema to `3`.
- Load schema-2 paired credential records by treating `createdAt` as the first
  `tokenIssuedAt` value.
- On pairing, set `tokenIssuedAt` to the pairing credential creation time.
- On successful manual rotation, preserve the original credential creation time
  and set `tokenIssuedAt` to the Hub's returned `rotatedAt` timestamp.
- Show a foreground Hub-card reminder when the current bearer issue time is older
  than the local reminder threshold.
- Do not contact the Hub, rotate automatically, create notifications, use
  WorkManager, or run background schedules for this slice.

## Consequences

The phone can now tell the operator that a paired bearer is stale without
mutating authority or adding background power cost. The reminder is deterministic
from local encrypted state and current foreground time, and it disappears after a
successful rotation because the stored bearer issue time advances.

Existing schema-2 paired records remain loadable and migrate in memory. The next
verified save writes schema 3.

This does not implement automatic token rotation schedules, background
notifications, trusted LAN rotation, or physical Moto G process-failure
validation.

## Rejected alternatives

- Use the original credential creation time for reminders after rotation.
  Rejected because it would keep warning even after a successful manual rotation.
- Automatically rotate when the threshold is crossed. Rejected because rotation
  can invalidate the only local bearer and must remain an explicit foreground
  action until durable scheduling and recovery semantics are validated.
- Add a background notification worker. Rejected for GOFFY LITE because it adds
  power, lifecycle, and audit behavior without being required for the first
  safe reminder.
