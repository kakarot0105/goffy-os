# Hub Audit

GOFFY Hub now keeps a bounded operator audit for paired-mode control-plane
activity. The audit is intentionally small: it records metadata for pairing,
WebSocket, and MCP events, not task payloads, user secrets, file contents, command
arguments, clipboard text, or model input/output.

## Storage

- In paired mode, the audit uses an owner-only SQLite database next to Hub state.
- Without a configured persistent audit path, the in-memory audit remains
  volatile and reports `volatile` integrity.
- Persistent rows are hash-chained with a stored chain tip and high-water mark.
- Retention pruning keeps the newest configured rows and reports a
  `retention_gap` instead of pretending the retained suffix is a full history.
- Row tampering, tail truncation, invalid metadata, unsafe paths, and unavailable
  storage fail closed for sensitive pairing mutations.

## Write Safety

Each persistent append runs inside `BEGIN IMMEDIATE` and assigns the next
sequence from the current database tip under the SQLite writer lock. This keeps
overlapping Hub processes from reusing stale in-memory sequence numbers when
they append to the same audit database.

Pairing redemption and paired-token rotation record a pre-mutation audit event
before changing credentials. If that pre-mutation audit write fails, the
credential mutation is rejected. If a post-mutation success audit write fails,
the already-committed credential state is not falsely reported as failed; the
pre-mutation event remains as bounded evidence.

## Retrieval

Owner/admin and paired self-audit retrieval expose bounded control-plane events
and integrity status. Returned records are redacted to operator metadata:
sequence, timestamp, source, action, outcome, principal kind, optional credential
ID, optional bounded detail code, and hash-chain fields.

## Still Open

- Certificate/public-key trusted Hub identity onboarding is not implemented.
- Trusted LAN operation is not supported.
- Task-result payload audit remains Android-local and redacted; Hub audit does
  not store task contents.
