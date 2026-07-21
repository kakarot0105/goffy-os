# ADR 0021: Android-pinned loopback Hub identity

## Status

Accepted

## Context

The Hub already creates an owner-only identity file and exposes a public
loopback-admin fingerprint. Pairing bundles, Android parsing, and encrypted
paired credential records still needed to carry that fingerprint so the phone
could show which Hub identity it paired with and reject unpinned legacy state.

This slice is still USB-loopback only. A displayed SHA-256 fingerprint is useful
operator context, but it is not a certificate, public-key proof, or LAN trust
mechanism.

## Decision

- Define `goffy.pairing.bundle.v2` and include `hubIdentity` fields
  `schemaVersion`, `hubId`, `fingerprint`,
  `createdAt`, `mode`, `verifiedBy`, and `trustedLanSupported=false` in
  that payload.
- Require Android to reject pairing bundles that omit or malform the Hub identity
  before any redemption request is sent.
- Include the same public identity in the redemption success response and require
  Android to reject pairing if it differs from the QR bundle identity.
- Store the public Hub identity pin inside the Android encrypted paired
  credential record and bump that record schema to `2`.
- Treat legacy or corrupted credential records without the pin as corrupt, delete
  the record and key, and disable Mac authority.
- Show the public fingerprint only for persistent paired links, not debug/manual
  development bearer links.

## Consequences

Operators can now inspect the same public Hub fingerprint on the Mac and Android
after QR pairing and restart. Android no longer silently restores older paired
records that lack a Hub identity pin.

This intentionally rejects `goffy.pairing.bundle.v1` for pinned Android pairing
and breaks compatibility with schema-1 Android credential records. Users must
create a fresh QR pairing bundle and pair again.

ADR 0035 supersedes this `goffy.pairing.bundle.v2` shape with
`goffy.pairing.bundle.v3` by adding an explicit USB-loopback-only trust contract.

## Rejected alternatives

- Accept legacy unpinned bundles for compatibility. Rejected because it would
  restore Mac authority without preserving the Hub identity boundary.
- Store only the fingerprint string. Rejected because preserving `hubId` and
  `createdAt` gives future trust onboarding enough public provenance to migrate.
- Treat the fingerprint as LAN trust. Rejected because no certificate or
  public-key proof exists yet.
