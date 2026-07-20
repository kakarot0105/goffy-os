# ADR 0023: Hash-chained Hub operator audit persistence

## Status

Accepted

## Context

ADR 0022 introduced a bounded in-memory Hub operator audit so operators could
inspect recent pairing, WebSocket, and MCP control-plane activity without
searching logs. That was useful but volatile. The next production step is to
retain audit evidence across Hub restart while preserving the same closed
metadata and no-secret boundary.

Persistent audit storage needs explicit integrity semantics because retention is
bounded. A pruned audit cannot prove the full historical chain, but it can prove
whether the retained segment is internally consistent.

## Decision

- In paired mode, derive `operator-audit.sqlite3` from the paired credential
  database directory and create it with owner-only permissions.
- Keep legacy non-paired mode memory-only.
- Store only closed audit metadata: sequence, timestamp, source, action, outcome,
  principal kind, optional credential ID, bounded detail code, previous hash, and
  event hash.
- Hash each row with a domain-separated SHA-256 digest over closed metadata plus
  the previous row hash.
- Store a DB-local chain tip in audit metadata and update it in the same
  `BEGIN IMMEDIATE` transaction as each inserted row, so simple tail truncation
  is not reported as a verified chain.
- Bound retention with `GOFFY_OPERATOR_AUDIT_MAX_EVENTS`, defaulting to 256.
- Report integrity as `verified`, `retention_gap`, `tamper_detected`, or
  `volatile`.
- Keep retrieval loopback bootstrap-admin-only and no-store.

## Consequences

Hub operator audit now survives paired-mode Hub restart and can detect row edits,
hash-link breaks, and simple tail truncation within the retained segment. A
`retention_gap` status means older rows were pruned, so the retained chain
verifies only from the oldest retained row forward.

This still does not make audit Android-visible, exportable, deletable, or full
forensic evidence. The chain tip is stored in the same SQLite database, so this
is not a defense against full database rollback or a coordinated rewrite by a
local operator with filesystem access. Those product controls remain future
work.

## Rejected alternatives

- Store raw request bodies or tool outputs. Rejected because the audit must not
  copy sensitive task data.
- Make persistence available without paired state. Rejected because paired mode
  already has an explicit local state directory and owner-only storage boundary.
- Treat pruned chains as fully verified. Rejected because retention removes the
  earlier hash evidence needed to prove the whole history.
