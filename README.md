# GOFFY OS

GOFFY OS is an open-source, phone-first agentic operating environment. An older
Android phone provides the command surface and small local engine; a macOS Hub
provides controlled access to heavier local capabilities. MCP-compatible typed
tools are the capability boundary.

> Status: Milestone 3 MCP core in progress. The current repo implements five
> offline PHONE actions and a discovery-gated SAFE Mac action, but physical Moto G
> verification, pairing, a standards-compliant MCP transport, and trusted LAN
> operation remain open.

## Current vertical slice

- Kotlin/Jetpack Compose GOFFY LITE home shell
- Deterministic route for exact `Show/Check [me] my Mac status`
- Offline deterministic route for battery status commands
- Permission-free, allowlisted `SAFE phone.battery.status` execution
- Privacy-minimized, offline `SAFE phone.device.info` execution
- Approval-gated `CONFIRM phone.note.create` with app-private SQLite persistence
- Approval-gated `CONFIRM phone.timer.create` through an allowlisted system Clock
- Approval-gated `CONFIRM phone.flashlight.set` with CameraManager callback verification
- Exact-task, exact-arguments, expiring, single-use phone approval grants
- Invocation-scoped authenticated WebSocket to `/ws/v1`
- Per-invocation discovery of the locally allowlisted Mac tool before execution
- FastAPI Hub bound to `127.0.0.1` by default
- GOFFY protocol `0.2.0` with MCP `2025-11-25`-aligned tool metadata
- Allowlisted, read-only `SAFE mac.system_info` tool
- Strict Kotlin codec plus typed Python protocol models
- Shared typed execution events with separate result, verified, and unverified states
- Shared fixture `protocol/fixtures/mac-system-info-flow.jsonl`
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

Tool access remains disabled when `GOFFY_HUB_TOKEN` is unset. Never commit a
real token. Use localhost for now; LAN remains unsupported until trusted TLS
and pairing exist. See [Hub setup](docs/setup/hub.md) for WebSocket usage.

`/ws/v1` is GOFFY's typed application protocol, not an MCP JSON-RPC endpoint.
Its discovery records intentionally mirror MCP tool schemas and annotations so
the same registry can back a standards-compliant MCP server in a later slice.

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

This is an Android application layer, not a flashable replacement ROM. A custom
ROM remains a later hardware-specific project after the agent runtime is proven.

## Verify the repository

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy hub/src protocol/python
.venv/bin/python -m build
.venv/bin/pytest -q
.venv/bin/python scripts/security_scan.py
```

Read [SECURITY.md](SECURITY.md) before exposing the Hub beyond localhost.
