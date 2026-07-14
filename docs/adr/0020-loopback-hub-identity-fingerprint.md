# ADR 0020: Loopback Hub identity fingerprint

- Status: Accepted
- Date: 2026-07-14

## Context

GOFFY needs a stable way to distinguish one paired Mac Hub from another before it
can support Android-side pinning, direct Hub audit retrieval, or any future
trusted LAN onboarding. The existing USB-loopback pairing bundle intentionally
declares `trustedLanSupported=false` and does not carry a public key or
certificate pin.

## Decision

- Create a local `hub-identity.json` file only when paired mode is explicitly
  enabled with `GOFFY_PAIRING_DATABASE_PATH`.
- Store it next to the pairing credential database and require owner-only file
  permissions.
- Store a random 32-byte identity seed, a generated Hub ID, and a creation
  timestamp.
- Derive a public fingerprint as `sha256:<64 lowercase hex characters>` from the
  identity seed with a domain-separated hash.
- Expose only the public identity document from `GET /admin/v1/hub-identity`.
- Keep the route loopback-only, bootstrap-admin-only, and no-store.
- Return `trustedLanSupported=false` until Android pinning and certificate or
  public-key proof exist.

## Consequences

Operators can now inspect a stable Hub fingerprint, and future Android onboarding
can pin that fingerprint before allowing higher-authority Mac workflows. This
also gives future Hub/MCP audit records a stable local Hub identifier without
using hostnames, serial numbers, MAC addresses, or account data.

This does not implement trusted LAN pairing, certificate pinning, public-key
signature proof, Android display/pinning UX, or a direct Hub/MCP audit store.

## Rejected Alternatives

- Expose host hardware identifiers: they are unnecessary and increase device
  fingerprinting risk.
- Put the identity seed or a future private key in the pairing bundle: the bundle
  is a short-lived transfer payload and must not carry long-lived private
  material.
- Add the fingerprint to `/health`: that endpoint is unauthenticated and should
  remain free of stable host identifiers.
- Claim LAN trust from this fingerprint alone: a displayed fingerprint is useful
  only after Android pins it and transport proof is implemented.
