# GOFFY OS

GOFFY OS is an open-source, phone-first agentic operating environment. An older
Android phone provides the command surface and small local engine; a macOS Hub
provides controlled access to heavier local capabilities. MCP-compatible typed
tools are the capability boundary.

> Status: Milestone 0 foundation. This repository is not yet a replacement
> Android ROM and the Android client does not yet connect to the Hub.

## Current vertical slice

- Kotlin/Jetpack Compose GOFFY LITE home shell
- FastAPI Hub bound to `127.0.0.1` by default
- Versioned, typed phone-to-Hub protocol models
- Authenticated WebSocket tool invocation endpoint
- Allowlisted, read-only `mac.system_info` tool
- Structured progress, result, error, and verification events
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
real token. See [Hub setup](docs/setup/hub.md) for WebSocket usage.

## Android setup

Install Android Studio with JDK 17 and Android SDK 36, then open `android/` as a
project. The minimum SDK is 26. Command-line verification is:

```bash
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug --no-daemon
```

See [Android setup](docs/setup/android.md) for emulator and Moto G real-device
steps.

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
