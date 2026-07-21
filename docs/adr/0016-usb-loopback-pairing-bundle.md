# ADR 0016: USB-loopback pairing bundle

- Status: Accepted
- Date: 2026-07-13

## Context

Android pairing originally accepted raw challenge JSON copied from the Mac. That
works for a debug operator, but a camera QR scanner needs a versioned payload
that includes both the one-time challenge and the Hub endpoint it is meant for.
At the same time, GOFFY does not yet have trusted LAN identity onboarding,
certificate pinning, or public-key pin transfer.

## Decision

- Add `POST /admin/v1/pairing/bundles`.
- Keep the route loopback-only and bootstrap-admin-only.
- Require the request Host header used to construct the bundle endpoint to be
  loopback.
- Return `Cache-Control: no-store` and `Pragma: no-cache`.
- Define `goffy.pairing.bundle.v1` as the QR payload shape.
- Include the exact `/ws/v1` endpoint, one raw challenge, and Hub identity
  metadata declaring:
  - `mode=usb_loopback`
  - `verifiedBy=loopback_admin_session`
  - `trustedLanSupported=false`
- Add a language-neutral JSON Schema and fixture under `protocol/`.
- Require Android's foreground pairing path to accept the bundle shape. The
  bundle endpoint must exactly match the currently configured endpoint.

## Consequences

The next camera QR scanner can pass the scanned string into the same Android
pairing parser already tested for the manual foreground field. The bundle makes
endpoint substitution and premature LAN trust explicit failure cases, while
preserving the current USB-loopback-only security model.

ADR 0021 supersedes this initial `goffy.pairing.bundle.v1` shape with
`goffy.pairing.bundle.v2` so Android can require and persist public Hub identity
metadata.

ADR 0035 supersedes `goffy.pairing.bundle.v2` with
`goffy.pairing.bundle.v3` so the bundle also carries the explicit
USB-loopback-only Hub identity trust contract.

This does not implement camera capture, QR decoding, trusted certificate
onboarding, LAN pairing, or automatic token rotation schedules. Hub-side paired
token rotation is handled by ADR 0018; Android manual rotation UX is handled by
ADR 0019.

## Rejected alternatives

- Continue accepting raw challenge JSON in Android onboarding: it would make the
  new endpoint and identity checks optional in the same user path.
- Claim TLS or LAN trust in the first bundle: the phone still has no trusted Hub
  public key or certificate pin.
- Put the access token in the bundle: credentials must remain returned exactly
  once from `/pairing/v1/redeem`.
