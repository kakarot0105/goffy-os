# ADR 0011: Redacted Android audit trail

- Status: Accepted
- Date: 2026-07-13

## Context

The Android timeline already shows observe-plan-act-verify progress for local
and Hub-backed tasks, but that history disappears when the app process stops.
Milestone 3 needs a persistent, user-visible audit slice that survives restart
without turning the timeline into a second authority channel, leaking sensitive
task content, or adding background work that does not fit GOFFY LITE hardware.

The first persistence increment is Android-local only. Direct Hub/MCP operator
audit remains deferred because GOFFY does not yet have a stable paired identity
for the user, device, and Hub session, and it does not yet have a user-visible
retrieval path for any second audit store.

## Decision

- Persist only terminal Android task records in app-private SQLite. A record may
  be written only after the task reaches `VERIFIED`, `UNVERIFIED`, `FAILED`, or
  `CANCELLED`.
- Disable Android backup and device transfer for the app's data. Uninstall
  removes the local audit records.
- Bound retention to the newest 50 terminal records.
- Store only closed metadata: audit schema version, GOFFY protocol version, task
  UUID, terminal timestamp, source, PHONE/MAC target, allowlisted tool name or
  `null`, SAFE/CONFIRM permission or `null`, terminal phase, approval outcome,
  and bounded event kinds (`OBSERVE`, `PLAN`, `AUTHORIZE`, `PREPARE`, `TOOL`,
  `RESULT`, `VERIFY`, `ERROR`).
- Accept only protocol versions listed as audit-compatible. A protocol bump must
  retain the prior compatible version or provide an explicit audit migration;
  unknown versions remain visible as discarded rows through `DEGRADED` state.
- Use audit database schema version 2. Its explicit version-1 migration rebuilds
  the table with protocol compatibility enforced by the typed model rather than
  a protocol-specific SQLite constraint, preserving valid terminal rows.
- Never persist raw command text, typed arguments, note text, row IDs, tool
  results, device info, approval text, event messages, endpoint or token values,
  free-form summaries, or verification checks.
- Restore audit as display-only history. Relaunch may show terminal cards, but
  never a structured result, pending approval, active task, or execution
  authority.
- Treat process death mid-task as no durable audit write. GOFFY must not create
  a synthetic success, unverified completion, or resumed approval after restart.
- Surface audit read failure, write failure, or corrupt/discarded rows as a
  visible `DEGRADED` state. That failure may reduce retained history, but it may
  not rewrite the task's execution phase or verification verdict already shown
  to the user.
- Use the existing bounded IO dispatcher. Do not add polling, WorkManager,
  background retry, or background repair for this increment.
- Defer explicit clear UI, cryptographic tamper evidence, and direct Hub/MCP
  operator audit until the paired-identity and retrieval prerequisites exist.

## Consequences

Android now keeps a bounded restart-stable history for terminal PHONE and MAC
tasks without persisting the sensitive content that produced those outcomes. The
history is intentionally incomplete: it is meant to show that a task ended, how
it ended, and what bounded policy labels applied, not to reproduce task inputs
or outputs.

Because restore is display-only, approval and execution authority remain
process-local. A restarted app cannot silently resume a pending approval, claim
that an in-flight task succeeded, or replay an old result as fresh work. Audit
failure is visible to the user as `DEGRADED`, but it does not retroactively
change the task outcome already observed in the live timeline.

This slice adds one small startup read and one small terminal write per task on
the existing IO dispatcher. No polling loop, retry worker, or extra service is
introduced.

## Rejected alternatives

- Persist full command text, typed arguments, note text, tool results, approval
  text, or verification summaries. This would turn the audit store into a second
  sensitive data channel and weaken the privacy boundary.
- Persist pending approvals, active tasks, or resumable execution state. That
  would let storage restoration blur the authority boundary and create ambiguous
  post-crash behavior.
- Write synthetic completion records during process restart recovery. GOFFY must
  not guess whether an interrupted task finished.
- Add background retry, polling, or WorkManager repair for audit writes. The
  store is bounded and user-visible, so silent background recovery would add
  complexity and battery cost without closing the authority gap.
- Build Hub-side or MCP-side operator audit first. Without stable paired
  identity and user-visible retrieval, a second audit store would be harder to
  interpret and easier to misuse than the Android-local slice.
- Add cryptographic tamper evidence in the first increment. The project still
  lacks the key-management, identity, and retrieval surfaces needed to make that
  guarantee inspectable to the user.

## References

- [Access app-specific files](https://developer.android.com/training/data-storage/app-specific)
- [Save data using SQLite](https://developer.android.com/training/data-storage/sqlite)
- [Back up user data with Auto Backup](https://developer.android.com/identity/data/autobackup)
- [Security recommendations for backups](https://developer.android.com/privacy-and-security/risks/backup-best-practices)
