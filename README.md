# GOFFY OS

GOFFY OS is an open-source, phone-first agentic operating environment. An older
Android phone provides the command surface and small local engine; a macOS Hub
provides controlled access to heavier local capabilities. MCP-compatible typed
tools are the capability boundary.

> Status: Milestone 2 phone engine in progress. The current repo implements three
> offline PHONE actions and the software path for one SAFE Mac action, but physical
> Moto G verification, pairing, and trusted LAN transport remain open.

## Current vertical slice

- Kotlin/Jetpack Compose GOFFY LITE home shell
- Deterministic route for exact `Show/Check [me] my Mac status`
- Offline deterministic route for battery status commands
- Permission-free, allowlisted `SAFE phone.battery.status` execution
- Privacy-minimized, offline `SAFE phone.device.info` execution
- Approval-gated `CONFIRM phone.note.create` with app-private SQLite persistence
- Exact-task, exact-arguments, expiring, single-use phone approval grants
- Invocation-scoped authenticated WebSocket to `/ws/v1`
- FastAPI Hub bound to `127.0.0.1` by default
- Versioned, typed phone-to-Hub protocol models
- Allowlisted, read-only `SAFE mac.system_info` tool
- Strict Kotlin codec plus typed Python protocol models
- Shared typed execution events with separate result and verification states
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

## Android setup

Install Android Studio with JDK 17 and Android SDK 36, then open `android/` as a
project. The minimum SDK is 26. Command-line verification is:

```bash
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug --no-daemon
```

See [Android setup](docs/setup/android.md) for the USB localhost debug flow.
Physical Moto G verification for this slice is still open.

To exercise the local mutation path, enter `Create a note saying Buy milk`. GOFFY
must show an approval card and perform no write until `Approve once` is tapped.
The resulting task is successful only after the stored row is re-read and matches
the approved text. Denial, cancellation, and the 60-second timeout invoke no tool.

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
