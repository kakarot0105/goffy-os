# ADR 0019: Android paired token rotation UX

- Status: Accepted
- Date: 2026-07-14

## Context

ADR 0018 added the Hub primitive for replacing a paired bearer while preserving
the same credential identity. Android still needed a user-visible way to request
rotation and a recovery rule for the dangerous case where the Hub commits a new
digest but the phone does not durably store the returned bearer.

Rotation is not background maintenance in this slice. It is a deliberate
foreground security action because it can invalidate the only local credential.

## Decision

- Expose manual rotation only for `PAIRED` Hub links, never for debug bearer
  links.
- Require an explicit confirmation dialog before rotation.
- Cancel active GOFFY work before rotation starts because the Hub closes live
  WebSocket and MCP sessions for the credential after rotation.
- Send exactly one authenticated loopback `POST /pairing/v1/rotate` request.
  Do not follow redirects and do not retry transport or HTTP failures.
- Require the returned `credentialId` to exactly match the stored paired
  credential.
- Preserve the original endpoint, credential ID, descriptive phone ID, and
  original credential creation time. Replace only the bearer.
- Activate the rotated bearer only after encrypted local persistence and
  read-back verification succeed.
- If Hub rotation, response validation, or local persistence is ambiguous or
  fails, disable Mac access, clear local paired authority on a best-effort basis,
  and mark the link `DEGRADED`. The user must re-pair and inspect Hub
  credentials from the Mac.

## Consequences

Android can now complete the paired-token rotation loop without exposing a raw
bearer in URLs, saved Compose state, audit rows, or stringified output. The
action remains foreground-only and adds no worker, polling loop, background
network task, or new permission, so it stays compatible with GOFFY LITE.

The fail-closed policy may require re-pairing even when the old token would have
remained valid. That is intentional because an ambiguous lost response can also
mean the old token is already dead and the new token is unrecoverable.

Automatic rotation schedules, rotation reminders, trusted LAN rotation, and
physical Moto G process-failure validation remain future work.

## Rejected alternatives

- Retry rotation after transport failure: unsafe because the first request may
  already have committed the new digest.
- Keep using the old local credential after ambiguous failure: misleading and
  can silently preserve stale authority.
- Clear local state before calling the Hub: worse crash behavior because a local
  failure would lose a still-current credential before the Hub has changed state.
- Make rotation automatic in the background: not acceptable until durable
  scheduling, power policy, and user-visible audit semantics exist.
