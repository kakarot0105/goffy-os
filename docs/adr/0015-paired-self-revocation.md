# ADR 0015: Paired self-revocation

- Status: Accepted
- Date: 2026-07-13

## Context

ADR 0014 made Android paired credentials durable and recoverable, but `Forget
local link` only removed phone-side authority. That was honest, but incomplete:
a retired phone still required bootstrap-admin revocation on the Mac, and a user
could reasonably expect the phone to revoke its own paired credential when it is
still online.

The revocation path must not allow a client to choose another credential ID,
must remain local-only until trusted Hub identity onboarding exists, and must not
turn an ambiguous lost response into a false success.

## Decision

- Add exact `DELETE /pairing/v1/self`.
- Keep the route loopback-only.
- Require an authenticated paired principal. Bootstrap-admin and missing
  credentials are rejected.
- Derive the revocation target from the authenticated principal's credential ID.
  The client supplies no target credential ID.
- Persist revocation before closing indexed live WebSocket and MCP sessions.
- Return only the revoked credential ID and `revoked: true`, with no-store cache
  headers.
- On Android, `Forget link` first disables Mac access in memory, cancels active
  work, joins any link job, and deletes the local encrypted credential.
- After the local delete attempt, Android makes exactly one self-revocation
  request for paired links. Development bearer links have no paired Hub record
  and skip remote revocation. The default pairing HTTP client disables connection
  retries and HTTP/HTTPS redirects.
- Android accepts the remote result only when the returned credential ID exactly
  matches the locally stored paired credential ID and `revoked` is true.
- Any transport failure, auth failure, false response, wrong credential ID,
  malformed body, oversized body, or non-loopback endpoint leaves remote
  revocation unverified. Android does not retry because a lost DELETE response
  may already have changed Hub state.
- The UI uses an explicit confirmation dialog and reports either verified Hub
  revocation, local-only deletion with unverified Hub revocation, or degraded
  local cleanup.

## Consequences

Retiring an online paired phone no longer depends on copying the credential ID to
the Mac admin route. The phone cannot revoke another credential because the Hub
chooses the target from authentication state. Offline forget still stops phone
authority immediately and clearly tells the user that Hub revocation needs Mac
inspection.

This adds one foreground HTTP DELETE during paired forget only. There is no
background worker, polling, retry loop, model load, or new Android permission, so
the behavior remains compatible with GOFFY LITE and API 26.

Token rotation, lost-phone administrator recovery, trusted LAN onboarding,
direct Hub/MCP operator audit, and physical Moto G process-failure testing remain
open.

## Rejected alternatives

- Client-supplied credential ID: unnecessary authority expansion and easier to
  misuse.
- Automatic retries: unsafe for an ambiguous DELETE whose response may be lost
  after the Hub persisted revocation.
- Remote revocation before local deletion: worse crash behavior because the
  phone could keep usable local authority if the app dies before cleanup.
- Expose this route to LAN now: trusted Hub identity onboarding is still absent.
