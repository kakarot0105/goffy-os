# ADR 0022: Bounded Hub operator audit

## Status

Superseded by ADR 0023 for paired-mode persistence

## Context

Stable paired credentials and a pinned loopback Hub identity now give Hub events
a meaningful principal boundary. Android already has a redacted terminal-task
audit trail, but the Hub still needed a direct way for the operator to inspect
pairing, WebSocket, and MCP control-plane activity without introducing a larger
persistent audit subsystem too early.

This slice must not store secrets, request bodies, tool outputs, arbitrary
headers, or free-form model summaries. It also must not imply forensic retention
or Android-side visibility before retention and tamper-evidence policy exists.

## Decision

- Add a bounded in-memory `OperatorAuditLog` for Hub control-plane events.
- Record closed metadata only: sequence, timestamp, source, action, outcome,
  principal kind, optional credential ID, and bounded detail code.
- Expose newest-first audit retrieval at `GET /admin/v1/audit/events`.
- Require loopback bootstrap administration for audit retrieval and mark
  responses `no-store`.
- Record successful pairing administration, successful challenge redemption,
  WebSocket connection outcomes, and MCP HTTP request outcomes.
- Keep retention memory-only and bounded by `GOFFY_OPERATOR_AUDIT_MAX_EVENTS`,
  defaulting to 256.

## Consequences

Operators can now inspect recent Hub/MCP control-plane activity from the Mac
without searching logs and without exposing tokens or tool results. This closes
the first direct Hub audit gap while keeping storage and disclosure risk small.

This initial volatile design was later extended by ADR 0023 with paired-mode
hash-chained SQLite persistence. Android retrieval, deletion, and export remain
separate future work.

## Rejected alternatives

- Persist audit rows immediately. Rejected because retention, deletion, export,
  schema migration, and tamper-evidence policy are not defined yet.
- Reuse application logs. Rejected because logs are not typed product state and
  can accidentally collect secrets or stack traces.
- Include request bodies or tool outputs. Rejected because audit should prove
  control-plane activity without copying sensitive task data.
