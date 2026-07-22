# ADR 0038: Phone-Local User-Approved Memory

## Status

Accepted.

## Context

GOFFY needs Jarvis-like continuity, but memory can easily become a privacy or
surveillance boundary if the agent stores facts implicitly. The first memory
slice must therefore be local, inspectable, bounded, and explicitly approved.

## Decision

Android now exposes three phone tools:

- `phone.memory.remember` stores one user-approved memory in app-private SQLite.
- `phone.memory.list` reads a bounded newest-first view of app-private memories.
- `phone.memory.forget_all` deletes all app-private memories after explicit
  approval and verifies the remaining count is zero.

Memory rows carry a fixed provenance value,
`user_approved_phone_command`. Stored text is limited to 512 characters, local
retention is capped to the newest 100 rows, and list output is capped to 20
entries. Persistent terminal audit stores only closed metadata and never stores
memory text or typed memory arguments.

## Consequences

- GOFFY gains a real local continuity primitive without adding cloud AI,
  background collection, or a broad database surface.
- Memory listing is currently command/timeline based. Per-memory edit/delete UI
  and retention controls remain future work.
- `forget_all` is intentionally the only destructive memory path in this slice;
  narrower per-row deletion needs its own approval wording and tests.
