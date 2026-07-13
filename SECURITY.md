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
- WebSocket tokens are passed in the `Authorization` header, never in URLs.
- The Android client keeps the development token in memory only and excludes it
  from saved UI state and string representations.
- Release Android clients require `wss://`; debug cleartext is limited to
  `localhost` and `127.0.0.1` for the documented USB port-reversal flow.
- Automatic reconnect occurs only before an invocation is sent. Sent requests
  are not replayed, and local cancellation does not claim Hub-side termination.
- Tool names are resolved only from an in-process allowlist.
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
- Errors returned to clients are stable codes without stack traces or secrets.

## Explicitly prohibited

- Generic terminal tools or arbitrary command strings
- Shell interpolation or `shell=True`
- Reading keychains, browser credential stores, SSH keys, or cloud credentials
- Recursive deletion outside an approved sandbox
- Background camera or microphone capture
- Disabling host security controls
- Silent LAN or public-network exposure
- Treating note text as SQL, a command, or additional authority
- Implicit timer intents or non-allowlisted Clock-handler dispatch
- Camera opening or image capture as part of the flashlight tool

See [the initial threat model](docs/security/threat-model.md) for remaining risks.
