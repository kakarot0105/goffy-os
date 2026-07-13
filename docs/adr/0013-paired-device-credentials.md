# ADR 0013: Paired-device credential boundary

- Status: Accepted
- Date: 2026-07-13

## Context

The original development bearer authenticated transport access but mapped every
caller to one operator. That could not support per-device MCP session ownership,
credential revocation, or a trustworthy future Hub audit. Android's current
protocol `deviceId` is process-generated and is not a durable security identity.

## Decision

- Enable paired mode only when `GOFFY_PAIRING_DATABASE_PATH` is explicitly set to
  an absolute path. Startup fails closed for an unsafe path, corrupt database, or
  unsupported schema.
- Require the Hub itself to remain bound to a local host while paired mode is
  enabled. Configured LAN TLS and allowlists do not override this guard.
- Keep `GOFFY_HUB_TOKEN` as a loopback bootstrap administrator credential. When
  paired mode is enabled it has pairing-admin scope only and cannot use `/ws/v1`
  or `/mcp`. When paired mode is disabled, its legacy SAFE-tool access remains for
  the existing USB development flow.
- Create challenges through authenticated loopback-only
  `POST /admin/v1/pairing/challenges`. Challenges contain 256 bits of randomness,
  live in memory for 120 seconds by default, are limited to three pending entries,
  allow at most five failed redemptions, and are consumed exactly once.
- Redeem through loopback-only `POST /pairing/v1/redeem`. The typed JSON body is
  capped at 2 KiB. Invalid requests and errors never echo pairing material, and
  successful secret-bearing responses set `Cache-Control: no-store`.
- Mint a random 256-bit paired bearer and return it once. Persist only a
  domain-separated SHA-256 digest plus bounded device metadata, generated
  `credentialId`, creation time, and optional revocation time.
- Treat `credentialId` as the durable principal. Client `deviceId` is descriptive
  setup metadata only and never grants authority.
- Use SQLite schema version 1 with parameterized statements, a 32-active-device
  cap, 64-row total retention cap, an owner-only `0600` database file, and no
  group/world-writable immediate parent directory.
- Give every paired principal SAFE-tool scope and a distinct MCP `client_id` and
  subject. MCP sessions therefore remain isolated across paired credentials.
- Revoke through authenticated loopback-only
  `DELETE /admin/v1/credentials/{credentialId}`. Persist revocation first, then
  terminate all indexed WebSockets and MCP sessions before returning success.
- Keep pairing and paired tool access off LAN. Trusted remote access requires a
  separate certificate provisioning and authorization design.

## Consequences

The Hub now has stable, revocable per-device identity without storing recoverable
bearers. Pairing survives Hub restart only after redemption; pending challenges
are intentionally discarded. Each authentication performs one bounded local
SQLite lookup off the event loop, comparing at most 32 digests.

The Android app does not yet drive these routes or persist the returned bearer.
Until Android secure storage and a guided QR exchange ship, paired mode is a Hub
operator API and the documented legacy USB token flow remains available only when
the pairing database is not configured. This is not MCP OAuth and does not yet
provide token rotation, trusted LAN pairing, or direct Hub/MCP operator audit.

## Rejected alternatives

- Use Android `deviceId` as the principal. It is not currently stable and is
  client-controlled metadata.
- Add pairing messages to `/ws/v1`. This would expand both protocol codecs and the
  Android transport before providing any security benefit over a narrow HTTP API.
- Store raw bearer or challenge values. Random token digests are sufficient for
  verification and make database disclosure less useful.
- Let the bootstrap token retain tool scope in paired mode. That would bypass
  stable identity and make revocation and audit incomplete.
- Enable pairing over configured LAN TLS. File-based TLS is not yet a trusted
  certificate onboarding story for the phone.

## References

- [Python `secrets`](https://docs.python.org/3/library/secrets.html)
- [Python `hashlib`](https://docs.python.org/3/library/hashlib.html)
- [Python `sqlite3`](https://docs.python.org/3/library/sqlite3.html)
- [RFC 6750 bearer token usage](https://www.rfc-editor.org/rfc/rfc6750.html)
