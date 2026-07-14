# ADR 0018: Paired token rotation

- Status: Accepted
- Date: 2026-07-13

## Context

Paired credentials are long-lived enough to survive Hub and Android restarts.
That makes revocation possible, but it also means a still-trusted phone needs a
way to replace its bearer without creating a second device identity or requiring
the bootstrap administrator token. Rotation must not let a client choose another
credential ID, must not leave the old bearer usable after success, and must not
silently turn concurrent stale requests into multiple valid returned bearers.

## Decision

- Add exact `POST /pairing/v1/rotate`.
- Keep the route loopback-only.
- Require an authenticated paired principal. Missing credentials and bootstrap
  administrators are rejected.
- Derive the rotation target from the authenticated principal's credential ID.
  The client supplies no target credential ID.
- Atomically re-check the presented current bearer digest while replacing the
  stored digest. A stale bearer that authenticated before another rotation cannot
  rotate again.
- Return the same `credentialId`, a new one-time `accessToken`, and `rotatedAt`
  with no-store cache headers.
- Persist only the new digest. Raw old and new bearers are never stored, listed,
  logged, or returned by administrator credential listing.
- After persistence, terminate all indexed live WebSocket and MCP sessions for
  the credential ID so existing sessions re-authenticate with the new bearer.
- Treat rotation conflicts as failures; do not retry automatically.

## Consequences

A paired phone can replace its bearer while preserving stable credential identity
and revocation history. The old bearer fails new WebSocket and MCP authentication
immediately after a verified rotation response, and old live sessions are closed.
Concurrent stale rotations fail closed instead of invalidating a newly returned
token.

The Hub API primitive is implemented first. Android-triggered scheduled or
manual rotation policy, user-visible recovery UX, trusted LAN rotation, and
direct Hub/MCP operator audit remain separate work.

## Rejected alternatives

- Client-supplied credential ID: unnecessary authority expansion.
- Revoke and re-pair: loses stable identity continuity and requires bootstrap
  administration.
- Rotate without checking the old bearer digest inside the write transaction:
  concurrent stale requests could invalidate a token already returned to the
  phone.
- Keep live sessions open after rotation: old bearer authority would continue
  beyond a verified rotation result.
