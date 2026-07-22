# ADR 0037: Device-Bound Android Approval Proof

## Status

Accepted.

## Context

GOFFY needs CONFIRM Mac actions over WebSocket, but a bearer-authenticated
`ApprovalResponse` alone is not enough authority. Any client holding a paired
bearer could otherwise forge approval without proving that the visible Android
approval surface was used.

The first CONFIRM Mac tool is `mac.apps.open`. It is allowlisted, schema-bound,
timeout-bounded, and non-destructive, but it still changes Mac state by opening
an application.

## Decision

Pairing now requires the Android client to register an ECDSA P-256 approval
public key using the `goffy.approval.public-key.v1` payload. Android creates the
private key in Android Keystore and never sends it to the Hub.

For an approved CONFIRM WebSocket invocation:

- The Hub issues a one-time `goffy.approval.v1` approval request bound to the
  principal, task ID, tool name, canonical argument SHA-256, issue time, and
  expiry.
- Android signs a canonical `goffy.approval.signed-payload.v1` byte payload
  containing the approval fields plus the paired credential ID and approved
  boolean.
- Android sends `goffy.approval.proof.v1` with algorithm
  `ECDSA_P256_SHA256`, the public-key SHA-256, and the base64 DER signature.
- The Hub verifies the public key hash against the paired credential, verifies
  the signature with PyCA `cryptography`, consumes the approval once, then
  executes the prepared tool.

Bootstrap/dev tokens and paired credentials without an approval public key can
discover SAFE tools only. MCP remains SAFE-only for this increment.

## Consequences

- CONFIRM WebSocket execution is now possible without introducing a generic
  shell, broad remote-control channel, or background approval.
- Pairing request size increased to 4 KiB to carry the public key metadata.
- Existing paired credentials without approval public keys must re-pair before
  using CONFIRM Mac tools.
- Android key attestation is not implemented yet. The Hub verifies possession of
  the registered private key, but it does not yet verify hardware-backed key
  provenance.
- Future trusted LAN pairing must add certificate pinning and server-side
  attestation verification before expanding this trust boundary.
