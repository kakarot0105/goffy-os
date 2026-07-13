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
- Tool authentication is disabled unless a token is explicitly configured;
  disabled means all tool requests are rejected.
- The exact `/mcp` endpoint uses the official MCP SDK's stateful Streamable HTTP
  transport. It accepts `POST` plus authenticated session `DELETE`, while `GET`
  server-push streams remain disabled. It is separate from GOFFY `/ws/v1`.
- MCP operations require initialization and the issued session ID. Sessions are
  credential-bound by the SDK, explicitly terminable, limited to eight active
  sessions by default, and idle-reaped after 60 seconds.
- MCP requests require the fail-closed bearer token and pass exact Host and Origin
  allowlists before JSON-RPC parsing. Local defaults include only loopback names.
- MCP request and response bodies share the configured Hub byte limit. The
  registry is capped at 32 tools, 24 KiB aggregate metadata, 8 KiB per capability,
  and 8 KiB per structured output.
- MCP execution defaults to two concurrent calls with a bounded one-second queue.
  Registry tool timeouts remain authoritative after admission.
- The current bearer token is a development authentication placeholder, not MCP
  OAuth, pairing, rotation, revocation, or device identity.
- WebSocket tokens are passed in the `Authorization` header, never in URLs.
- The Android client keeps the development token in memory only and excludes it
  from saved UI state and string representations.
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
  invocation; MCP clients must explicitly re-list tools because push is disabled.
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
- Flashlight execution requests no `CAMERA` permission, service, receiver, or
  background worker. Its short-lived `TorchCallback` is unregistered after success,
  failure, timeout, or cancellation.
- Flashlight verification is point-in-time: a matching callback proves the approved
  state at completion, not exclusive ownership or future persistence.
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

See [the initial threat model](docs/security/threat-model.md) for remaining risks.
