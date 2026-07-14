# GOFFY OS

GOFFY OS is an open-source, phone-first agentic operating environment. An older
Android phone provides the command surface and small local engine; a macOS Hub
provides controlled access to heavier local capabilities. MCP-compatible typed
tools are the capability boundary.

> Status: Milestone 3 MCP core in progress. The current repo implements five
> offline PHONE actions, a discovery-gated SAFE Mac action, an official MCP
> Streamable HTTP boundary, stable Hub paired-device credentials, Keystore-backed
> Android pairing restore, and a persistent user-visible Android audit trail
> for the newest 50 terminal tasks. MCP tool-list changes now stream with
> bounded, session-local reconnect replay. Paired phones can now forget locally
> and ask the Hub once to revoke the exact matching credential over loopback.
> Guided QR pairing, physical Moto G verification, direct Hub/MCP operator audit,
> token rotation, and trusted LAN operation remain open.

## Current vertical slice

- Kotlin/Jetpack Compose GOFFY LITE home shell
- Deterministic route for exact `Show/Check [me] my Mac status`
- Offline deterministic route for battery status commands
- Permission-free, allowlisted `SAFE phone.battery.status` execution
- Privacy-minimized, offline `SAFE phone.device.info` execution
- Approval-gated `CONFIRM phone.note.create` with app-private SQLite persistence
- Approval-gated `CONFIRM phone.timer.create` through an allowlisted system Clock
- Approval-gated `CONFIRM phone.flashlight.set` with CameraManager callback verification
- Immutable, bounded PHONE capability registry with MCP-shaped closed schemas
- Exact-task, exact-arguments, expiring, single-use phone approval grants
- Persistent, user-visible Android audit trail with app-private SQLite retention
  for the newest 50 terminal tasks
- Invocation-scoped authenticated WebSocket to `/ws/v1`
- Per-invocation discovery of the locally allowlisted Mac tool before execution
- FastAPI Hub bound to `127.0.0.1` by default
- GOFFY protocol `0.2.0` with MCP `2025-11-25`-aligned tool metadata
- Official, authenticated MCP Streamable HTTP endpoint at exact `/mcp`
- MCP initialization, `tools/list`, and registry-backed `tools/call`
- Bounded, fail-closed Hub tool-health checks
- Authenticated MCP tool-list change notifications with bounded reconnect replay
- Explicit loopback pairing with digest-only, revocable per-device Hub credentials
- Foreground Android challenge redemption with API-26 Keystore AES-GCM storage,
  verified restart restore, and paired self-revocation
- Allowlisted, read-only `SAFE mac.system_info` tool
- Strict Kotlin codec plus typed Python protocol models
- Shared typed execution events with separate result, verified, and unverified states
- Shared fixture `protocol/fixtures/mac-system-info-flow.jsonl`
- Shared PHONE capability snapshot `shared/fixtures/phone-tool-capabilities.json`
- Unit, integration, type, lint, and security checks

The previous browser concept is preserved in [`prototype/web-shell`](prototype/web-shell).

## Repository map

```text
android/       Android app and future phone-local capabilities
hub/           FastAPI Hub, auth boundary, routing, audit, and tools
mcp-servers/   MCP server module placeholders
protocol/      Versioned schemas and shared Python protocol package
shared/        Cross-component constants and fixtures
docs/          Architecture, ADRs, security, and setup guides
scripts/       Verification and security tooling
tests/         Cross-component integration tests
```

## Hub quick start

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token' .venv/bin/goffy-hub
```

The Hub listens only on `127.0.0.1:8787` by default. Check it with:

```bash
curl http://127.0.0.1:8787/health
```

Legacy tool access remains disabled when `GOFFY_HUB_TOKEN` is unset; paired mode
can still authenticate previously issued active credentials. Never commit a real
token. The default command above is legacy USB development mode. To enable
stable paired identity, configure the explicit state path and follow
[Hub setup](docs/setup/hub.md). Pairing remains loopback-only and trusted LAN use
is still unsupported. Android can now redeem the complete challenge JSON through
the foreground Hub card over USB loopback and restores the encrypted credential
after restart; QR transfer and token rotation remain open.
With the Hub running, verify the official MCP path in another terminal:

```bash
GOFFY_HUB_TOKEN='replace-with-the-same-development-token' .venv/bin/python scripts/demo_mcp.py
```

`/ws/v1` is GOFFY's typed application protocol, not an MCP JSON-RPC endpoint.
`/mcp` is the separate session-aware MCP `2025-11-25` JSON-RPC endpoint. Both are
backed by the same fail-closed typed tool registry; neither provides arbitrary
shell execution.

The Hub seals its registry before serving, checks registered tools locally at
startup and every 30 seconds by default, and removes an unhealthy tool from both
Android discovery and MCP execution. Android discovers before each invocation;
MCP clients receive `notifications/tools/list_changed` and then re-run `tools/list`.
Missed notifications can be replayed within the same live MCP session. `/health`
reports aggregate readiness, bounded tool counts, and registry revision without
exposing probe errors or tool names.

## Android setup

Install Android Studio with JDK 17 and Android SDK 36, then open `android/` as a
project. The minimum SDK is 26. Command-line verification is:

```bash
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease --no-daemon
python3 scripts/security_scan.py --require-merged-manifests
```

See [Android setup](docs/setup/android.md) for the USB localhost debug flow.
Physical Moto G verification for this slice is still open.

To exercise the local mutation path, enter `Create a note saying Buy milk`. GOFFY
must show an approval card and perform no write until `Approve once` is tapped.
The resulting task is successful only after the stored row is re-read and matches
the approved text. Denial, cancellation, and the 60-second timeout invoke no tool.

`Set a timer for 5 minutes` uses the same one-time approval boundary, then pins
Android's documented timer action to an allowlisted, enabled, exported system
Clock component. GOFFY runs no countdown service or polling loop. Verification
checks the exact requested duration and documented-contract dispatch receipt, but
the task ends `UNVERIFIED` because Android does not expose the Clock app's private
timer state. The Clock app owns the timer after dispatch.

`Turn on the flashlight` and `Turn off the torch` use the same exact one-time
approval boundary. GOFFY selects a back-facing flash, changes it without opening
the camera, and reports `VERIFIED` only after `TorchCallback` observes the approved
state. This verification is point-in-time; Android permits other apps or camera
resource pressure to change the torch later.

All five PHONE tools are declared in one sorted, immutable local registry. The
deterministic router reads each PHONE permission from that registry, and the
gateway independently rechecks tool name, target, permission, typed arguments,
and the compiled timeout before touching an Android source. Registry metadata is
descriptive, not authorization: CONFIRM tools still require an exact, expiring,
single-use approval and are not exported through the Hub MCP endpoint.

Android also persists the newest 50 terminal task cards in app-private SQLite
and restores them into the visible timeline after restart. Stored audit data is
closed metadata only: audit schema and protocol versions, task UUID and time,
source, PHONE or MAC target, allowlisted tool or `null`, SAFE or CONFIRM
permission or `null`, terminal phase, approval outcome, and bounded event kinds.
It never stores raw command text, typed arguments, note text, row IDs, tool
results, device info, approval text, event messages, endpoint or token values,
free-form summaries, or verification checks. Records are written only after
`VERIFIED`, `UNVERIFIED`, `FAILED`, or `CANCELLED`, so process death mid-task
creates no synthetic success. Read or write failure visibly degrades the audit
badge and may leave affected history in memory only; corrupt rows are discarded
while valid restored rows remain visible with a discarded-row count. None of
these failures rewrites the execution verdict, and GOFFY performs no polling,
WorkManager retry, or background repair.
Android backup and device transfer are disabled for app data; uninstall removes
the records. The paired Hub bearer is stored separately as one bounded AES-GCM
record in `noBackupFilesDir`; its 256-bit key remains non-exportable in Android
Keystore. A write is activated only after read-back verification. Corrupt or
undecryptable state is deleted and visibly disables Mac access. `Forget link`
removes the phone copy first; paired links then make exactly one authenticated
loopback self-revocation request for the stored credential ID. If the Hub cannot
verify it, the phone reports local deletion with remote revocation unverified.
Direct Hub/MCP operator audit remains future work.

This is an Android application layer, not a flashable replacement ROM. A custom
ROM remains a later hardware-specific project after the agent runtime is proven.

## Verify the repository

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy hub/src protocol/python
.venv/bin/python -m build
.venv/bin/python -m pytest -q
.venv/bin/python scripts/security_scan.py
```

Read [SECURITY.md](SECURITY.md) before exposing the Hub beyond localhost.
