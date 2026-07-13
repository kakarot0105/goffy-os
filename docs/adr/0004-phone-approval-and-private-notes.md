# ADR 0004: Phone approval grants and private notes

- Status: Accepted
- Date: 2026-07-13

## Context

The first phone tools are read-only and SAFE. Note creation is the first local
mutation and must prove that GOFFY can request explicit approval, avoid action
before approval, prevent replay or substitution, verify the resulting state, and
remain lightweight on an API 26 device.

## Decision

- Route only anchored `Create/Make [me] a note saying/that says ...` commands to
  `PHONE / phone.note.create / CONFIRM`; captured text is data, never authority.
- Reject blank, control-character, format-character, and over-2,000-character text.
- Keep a task in `AWAITING_APPROVAL` and invoke no gateway or storage source until
  the user chooses `Approve once`.
- Expire pending approval after 60 seconds. Denial, cancellation, and expiry are
  terminal and state that no phone tool was invoked.
- Bind each grant to the task ID, exact tool, typed arguments, and deadline. The
  gateway checks the deadline with its own clock and rejects reused task IDs and
  consumed grants.
- Store notes with Android's app-private SQLite APIs. Disable backup, request no
  storage permission, bind values with `ContentValues` and query selection
  arguments, and never interpolate note text into SQL.
- Insert and re-read the exact row in one transaction. Emit a successful
  verification event only when ID, text, and timestamp satisfy the typed contract.
- Run database work on the existing bounded IO execution path and truncate note
  summaries/previews in the timeline.

## Consequences

GOFFY now has a real foreground approval-to-mutation vertical slice with no cloud
or Hub dependency. Approval state is process-local; process death cancels it rather
than resuming authority. Notes survive normal app restarts but are removed on
uninstall. A note viewer, editing, deletion, retention policy, encrypted-at-rest
policy beyond platform storage, and process-persistent audit log remain future work.
Cancellation before approval guarantees no invocation; cancellation after the
database transaction starts is reported as non-guaranteed rather than as rollback.

JVM tests cover routing, lifecycle ordering, denial, cancellation, expiry, argument
substitution, replay, source isolation, typed output, and verification. SQLite and
touch behavior still require the documented physical-device pass.

## References

- [App-specific storage](https://developer.android.com/training/data-storage/app-specific)
- [Data and file storage overview](https://developer.android.com/training/data-storage)
- [SQLite injection risks](https://developer.android.com/privacy-and-security/risks/sql-injection)
- [`SQLiteOpenHelper`](https://developer.android.com/reference/android/database/sqlite/SQLiteOpenHelper)
