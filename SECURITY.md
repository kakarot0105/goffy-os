# Security Policy

GOFFY OS controls real devices and developer machines. Security defects can have
material consequences, so the project defaults to denial and narrow capability
grants.

## Supported versions

Only the latest commit on the default branch is supported during pre-alpha
development. No production security guarantee is made yet.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability. Until a private
security contact is published, send the maintainer a private GitHub security
advisory. Include impact, reproduction steps, and the affected commit. Do not
include real credentials or unrelated personal data.

## Security boundaries

- Hub network binding is `127.0.0.1` by default.
- Non-local binding requires explicit LAN mode and configured TLS files.
- Legacy tool authentication is disabled unless a bootstrap token is explicitly
  configured. In paired mode, tool access remains disabled until at least one
  active paired credential exists.
- Paired mode requires an explicit absolute `GOFFY_PAIRING_DATABASE_PATH`. The
  bootstrap token then has loopback pairing-admin scope only and cannot access
  `/ws/v1` or `/mcp`.
- Paired mode rejects a non-local Hub bind even if LAN mode, TLS files, and MCP
  allowlists are configured. Paired tool credentials are local-only in this slice.
- Pairing challenge creation, redemption, credential listing, administrator
  revocation, and paired self-revocation are loopback-only even when LAN binding
  guards are configured. Challenge creation also requires bootstrap administration.
- Challenges are memory-only, random, one-time, 120 seconds by default, capped at
  three pending entries, and invalidated after five failed attempts. Redemption
  JSON is capped at 2 KiB, validation errors never echo secret input, and
  secret-bearing success responses disable caching.
- Pairing bundles wrap one challenge in the versioned
  `goffy.pairing.bundle.v2` QR payload shape. The Hub creates them only through
  loopback bootstrap administration, requires a loopback Host header, marks them
  no-store, and includes the public Hub ID, stable SHA-256 fingerprint, creation
  timestamp, and `trustedLanSupported=false`. Redemption success responses carry
  the same public identity so Android can reject a mismatch before persistence.
- In paired mode, the Hub creates an owner-only `hub-identity.json` file next to
  the pairing credential database. `GET /admin/v1/hub-identity` is loopback-only,
  bootstrap-admin-only, no-store, and returns only a stable Hub ID, SHA-256
  fingerprint, creation timestamp, and `trustedLanSupported=false`. It never
  exposes the private identity seed and does not implement LAN trust, certificate
  pinning, or remote identity proof.
- `scripts/create_pairing_qr.py` creates local operator QR artifacts only from an
  HTTP loopback Hub URL, sends the bootstrap token in an `Authorization` header,
  validates the returned bundle shape, and writes the SVG with owner-only file
  permissions. The SVG is a short-lived secret because it contains the challenge
  token encoded in QR modules. The security scan rejects the default artifact
  filename and the generator's non-secret SVG marker.
- Paired bearers contain 256 bits of randomness and are returned once. SQLite
  stores only a domain-separated SHA-256 digest, generated credential ID, bounded
  device metadata, and timestamps in a `0600` file. Active credentials are capped
  at 32 and total retained rows at 64.
- The exact `/mcp` endpoint uses the official MCP SDK's stateful Streamable HTTP
  transport. It accepts `POST`, authenticated session `GET` for server events,
  and authenticated session `DELETE`. It is separate from GOFFY `/ws/v1`.
- MCP operations require initialization and the issued session ID. Paired sessions
  are bound to a unique credential-ID principal by the SDK, explicitly terminable,
  limited to eight active sessions by default, and idle-reaped after 60 seconds. A
  connected event stream remains counted and is server-rotated after 45 seconds
  before bounded reconnect.
- MCP requests require the fail-closed bearer token and pass exact Host and Origin
  allowlists before JSON-RPC parsing. Local defaults include only loopback names.
- MCP JSON request and response bodies share the configured Hub byte limit. SSE
  only carries fixed tool-list change notifications. Replay is isolated per
  session and capped at 64 events and 16 KiB; tool results are never retained. The
  registry is capped at 32 tools, 24 KiB aggregate metadata, 8 KiB per capability,
  and 8 KiB per structured output.
- MCP execution defaults to two concurrent calls with a bounded one-second queue.
  Registry tool timeouts remain authoritative after admission.
- The Hub keeps a bounded operator audit for pairing, WebSocket, and MCP
  control-plane events. `GET /admin/v1/audit/events` is loopback-only,
  bootstrap-admin-only, no-store, newest-first, and limited to 256 returned rows.
  Stored fields are closed metadata only: sequence, timestamp, source, action,
  outcome, principal kind, optional credential ID, bounded detail code,
  previous hash, and event hash.
- In paired mode, the Hub persists operator audit rows to owner-only
  `operator-audit.sqlite3` beside the credential store. Rows are hash-chained
  with a domain-separated SHA-256 digest over closed metadata and the previous
  row hash. Retrieval reports `verified`, `retention_gap`, or
  `tamper_detected`. The DB-local chain tip detects simple tail truncation, but
  this is not a defense against full database rollback or a coordinated rewrite
  by a local operator with filesystem access. Legacy non-paired mode remains
  memory-only and reports `volatile`.
- The Hub operator audit never stores bearer tokens, pairing tokens, request
  bodies, command text, typed arguments, tool outputs, stack traces, free-form
  summaries, or arbitrary header values. Retention is bounded by
  `GOFFY_OPERATOR_AUDIT_MAX_EVENTS` and defaults to 256.
- Paired credentials are not MCP OAuth. Loopback token rotation is implemented for
  the Hub and a confirmed Android foreground action, but automatic rotation
  schedules and trusted LAN onboarding remain unimplemented.
- Paired token rotation is loopback-only and paired-principal-only. The Hub derives
  the credential ID from authentication, atomically verifies that the presented
  bearer digest is still current before replacing it, returns the same credential
  ID plus a new bearer with no-store headers, and closes indexed live WebSocket
  and MCP sessions for that credential.
- Revocation persists before the Hub terminates every indexed live WebSocket and
  MCP session for that credential and releases its capacity slot. New
  authentication checks the digest store; revoked state survives restart.
- WebSocket tokens are passed in the `Authorization` header, never in URLs.
- Android redeems pairing challenges only against a loopback endpoint and never
  retries redemption. `MainActivity.onStop()` cancels and joins enrollment before
  local cleanup. The temporary challenge input is foreground-only,
  password-masked, bounded to 2 KiB, and excluded from saved Compose state, audit
  rows, URLs, and error text. Bundles missing the public Hub identity fingerprint
  are rejected before any redemption request. If the Hub redemption response
  returns different public identity metadata, Android rejects pairing before
  persistence. Persistent paired activation requires encrypted read-back of the
  bearer plus the pinned Hub identity; legacy records without a pin fail closed
  and are deleted. The visible fingerprint is public loopback identity metadata
  only and is not a certificate, public-key proof, or LAN trust grant.
- Android QR transfer is limited to the visible pairing setup flow. `Scan QR`
  requests `CAMERA` only from that foreground action, binds CameraX preview and
  image analysis to the Activity lifecycle, decodes QR codes only with ML Kit,
  stores no frame, performs no background capture, and shuts down analysis when
  the scanner closes, the Activity stops, or one payload is captured. The scanned
  value only populates the existing bounded pairing-bundle field; redemption still
  goes through the typed loopback parser and explicit `Pair phone` action.
- A returned paired bearer is activated only after one bounded record is encrypted
  with an API-26 Android Keystore 256-bit AES-GCM key, atomically stored under
  `noBackupFilesDir`, re-read, decrypted, and exactly verified. The authenticated
  record binds the exact endpoint, credential ID, descriptive phone ID, bearer,
  schema version, and creation time.
- Corrupt, oversized, schema-incompatible, or undecryptable paired state fails
  closed, deletes the local encrypted record and key, and never falls back to the
  legacy development credential. Restore performs no network probe or background
  repair. Backup and device transfer remain disabled for all app data.
- The legacy manual bearer field is compiled into debug behavior only, remains
  memory-only, and is excluded from saved UI state and string representations.
- `Forget link` cancels and joins foreground enrollment before deleting the
  encrypted record and Keystore key. For paired links, Android then makes exactly
  one loopback `DELETE /pairing/v1/self` request authenticated by the stored
  bearer. The Hub derives the target credential ID from the authenticated
  principal, persists revocation, terminates indexed live WebSocket and MCP
  sessions, and returns the revoked credential ID. Android treats any lost,
  mismatched, false, or error response as remote revocation unverified; it does
  not retry an ambiguous DELETE.
- `Rotate token` requires an explicit confirmation and runs only for paired
  loopback links. Android cancels active work before the request, accepts only a
  matching returned credential ID, preserves the existing endpoint, credential ID,
  descriptive phone ID, and original creation time, and activates the new bearer
  only after encrypted read-back verification succeeds.
- Android makes exactly one rotation request and does not retry ambiguous
  transport or HTTP failures. If Hub rotation, response validation, or local
  persistence fails, Android disables Mac access, best-effort clears local paired
  authority, marks the link degraded, and requires re-pairing plus Mac-side
  credential inspection.
- The bearer is decrypted into process memory while the active ViewModel owns the
  Hub connection configuration. Rooted-device/process compromise is outside this
  pre-alpha storage guarantee. Trusted certificate pin onboarding and
  automatic token rotation schedules are not implemented.
- Release Android clients require `wss://`; debug cleartext is limited to
  `localhost` and `127.0.0.1` for the documented USB port-reversal flow.
- Automatic reconnect occurs only before an invocation is sent. Sent requests
  are not replayed, and local cancellation does not claim Hub-side termination.
- MAC invocation requires an authenticated, same-socket capability discovery
  preflight. Discovery is bound to one locally allowlisted tool and consumed by
  one invocation attempt; it cannot grant authority for an unknown tool.
- Android validates the exact `mac.system_info` tool version, target, permission,
  schema subset, and safety annotations before sending invocation bytes. Configured
  timeout metadata is range-checked rather than treated as authority.
- Hub registration currently rejects every non-`SAFE`, non-read-only Mac tool.
  SAFE metadata must also be non-destructive, idempotent, closed-world, and use
  closed object schemas. CONFIRM and SENSITIVE tools remain unavailable until an
  explicit authorization protocol exists.
- A complete Android Hub attempt is bounded to 35 seconds. Timeout cancels the
  socket and reports failure without retrying an ambiguously delivered invocation.
- The Hub rejects duplicate message IDs on a connection, caps each connection at
  64 unique messages, and applies the configured byte limit to inbound and outbound
  envelopes. Cross-connection replay protection remains a pairing milestone.
- Tool names are resolved only from an in-process allowlist.
- The Hub registry is sealed before serving. Every registered tool has a local,
  timeout-bounded health probe; at most four probes run concurrently, and timeout,
  exception, false, or non-Boolean results all collapse to unavailable without
  exposing internal details.
- Tool health can only remove or restore an already-registered SAFE definition.
  It cannot add a tool, alter metadata, change permission, or bypass argument and
  output validation. Admission rechecks health and arguments before `accepted`;
  an admitted invocation uses that exact prepared state while later health changes
  block new admissions.
- Health checks run once before startup completes and every 30 seconds by default.
  The unauthenticated health endpoint exposes aggregate readiness, counts, and a
  revision only, not names or probe failures. Android discovers before every Mac
  invocation. Initialized MCP clients that have listed tools receive an empty
  `notifications/tools/list_changed` signal and must explicitly re-list to read
  current state. Opaque replay cursors work only for the same authenticated live
  session. Unknown or evicted cursors receive only a fresh re-list signal, never
  another session's history. Session termination, idle expiry, and Hub restart
  discard replay state.
- Android's immutable PHONE registry is bounded to 16 entries and 32 KiB. Every
  descriptor targets PHONE, uses a closed object schema, has a 30-second maximum
  timeout, and is limited to SAFE or CONFIRM permission.
- The PHONE registry and its shared fixture are descriptive compatibility data,
  not executable authority. The gateway rechecks compiled name, target, permission,
  typed arguments, timeout, and approval before any Android source is accessed.
- PHONE CONFIRM descriptors are not exported through MCP. Remote discovery,
  fixtures, and annotations cannot add a route, downgrade a permission, change an
  Android manifest grant, or mint an approval.
- `phone.battery.status` performs one foreground-requested BatteryManager read,
  validates its typed output, and requires no Android permission or background receiver.
- `phone.device.info` returns only manufacturer, user-visible model, Android release,
  and SDK level. It excludes hardware, advertising, account, network, and build identifiers.
- `phone.note.create` requires a visible one-time approval bound to the task ID,
  tool, exact typed arguments, and expiry. Replayed, changed, stale, or expired grants fail closed.
- Notes use the app-private SQLite database, Android backup is disabled, SQL values
  are bound through `ContentValues` and selection arguments, and every insert is
  re-read inside the transaction before verification is reported.
- `phone.timer.create` requires the same exact-task, exact-argument, expiring
  approval. It resolves only an enabled, exported, allowlisted system Clock
  handler, rejects the Android chooser and third-party handlers, then pins an
  explicit component.
- Timer dispatch uses Android's normal `SET_ALARM` permission and one narrow
  `ACTION_SET_TIMER` package query. It requests no exact-alarm, notification,
  foreground-service, boot, or broad package-query permission.
- A timer result is a dispatch receipt for the exact approved duration and explicit
  Clock component. The task ends `UNVERIFIED`; GOFFY does not claim that the Clock
  honored the request or expose private Clock state it cannot read.
- `phone.flashlight.set` requires exact-task, exact-state, expiring, single-use
  approval. It selects a deterministic back-facing flash candidate and never opens
  a camera stream or captures an image.
- Flashlight execution never requests or uses the QR scanner's `CAMERA`
  permission, service, receiver, or background worker. Its short-lived
  `TorchCallback` is unregistered after success, failure, timeout, or
  cancellation.
- Flashlight verification is point-in-time: a matching callback proves the approved
  state at completion, not exclusive ownership or future persistence.
- Android persists a redacted terminal-task audit trail in app-private SQLite.
  Each row is written only after `UNVERIFIED`, `VERIFIED`, `FAILED`, or
  `CANCELLED`; process death mid-task records no synthetic success.
- Audit retention is bounded to the newest 50 terminal records. Stored fields
  are closed metadata only: audit schema/protocol versions, task UUID and time,
  source, PHONE/MAC target, allowlisted tool or `null`, SAFE/CONFIRM permission
  or `null`, terminal phase, approval outcome, and bounded event kinds.
- The Android audit never stores raw command text, typed arguments, note text,
  row IDs, tool result data, device info, approval text, event messages, endpoint
  or token values, free-form summaries, or verification checks.
- Restored audit entries are display-only, result-free terminal cards. They
  cannot recreate a pending approval, active task, structured result, or
  execution authority.
- Audit read/write/corrupt-row failures visibly degrade the timeline to
  memory-only history or a discarded-row count, but do not rewrite the task
  phase or verification verdict already shown to the user. The app schedules no
  background retry or WorkManager recovery.
- Android backup and device-to-device transfer are disabled for app data, and
  uninstall removes local audit records.
- Android-side Hub/MCP audit retrieval, user-directed export/deletion, and full
  forensic policy remain future work. A retained hash chain with
  `retention_gap` proves only the retained segment, not pruned rows.
- CI validates both the strict source manifest and freshly merged debug and release
  manifests, rejecting permission variants, undeclared hardware features, and
  non-intent package queries.
- `mac.system_info` uses Python standard-library APIs and never invokes a shell.
- Protocol inputs reject unknown fields and unsupported versions.
- GOFFY protocol `0.2.0`, MCP metadata revision `2025-11-25`, and individual tool
  contract versions are separate compatibility boundaries.
- Errors returned to clients are stable codes without stack traces or secrets.

## Explicitly prohibited

- Generic terminal tools or arbitrary command strings
- Shell interpolation or `shell=True`
- Reading keychains, browser credential stores, SSH keys, or cloud credentials
- Recursive deletion outside an approved sandbox
- Background camera or microphone capture
- Disabling host security controls
- Silent LAN or public-network exposure
- Using health results to register tools or expand capability authority
- Treating note text as SQL, a command, or additional authority
- Treating PHONE capability metadata or fixtures as authorization
- Implicit timer intents or non-allowlisted Clock-handler dispatch
- Camera opening or image capture as part of the flashlight tool
- Persisting QR frames or redeeming a scanned bundle without a visible pairing action
- Committing, logging, or cloud-syncing generated pairing QR SVG artifacts
- Persisting raw commands, typed arguments, note text, tool results, device info,
  approval text, event messages, endpoint or token values, free-form summaries,
  or verification checks in the Android audit trail
- Restoring audit rows as pending approval state, active execution, structured
  result data, or resumable authority
- Treating a `retention_gap` Hub operator audit chain as complete forensic
  evidence for pruned rows
- Exposing Hub operator audit to Android before user-visible retrieval,
  deletion/export controls, and redaction policy are implemented

See [the initial threat model](docs/security/threat-model.md) for remaining risks.
