# GOFFY OS

GOFFY OS is an open-source, ROM-first agentic operating system project for
repurposing an older Android phone into a dedicated Jarvis-like device. The
short-term Android app remains a bootstrap, validation, and fallback layer; the
target product is a GOFFY-controlled Android ROM or GSI-derived system image
when the exact Moto hardware can support it safely. A macOS Hub provides
controlled access to heavier local capabilities. MCP-compatible typed tools are
the capability boundary.

> Status: ROM feasibility plus Milestone 3 MCP core in progress. The current
> repo now treats ROM/GSI feasibility for the exact Moto G 2025 `kansas` target
> as the primary product track, with the launcher/app layer kept for safe
> validation and fallback. The current repo implements five
> offline PHONE actions, a discovery-gated SAFE Mac action, an official MCP
> Streamable HTTP boundary, stable Hub paired-device credentials, Keystore-backed
> Android pairing restore, and a persistent user-visible Android audit trail
> for the newest 50 terminal tasks. MCP tool-list changes now stream with
> bounded, session-local reconnect replay. Paired phones can now forget locally
> and ask the Hub once to revoke or rotate the exact matching credential over
> loopback. The Hub now emits a versioned USB-loopback pairing bundle with its
> public loopback identity fingerprint, and Android can scan that bundle through
> a foreground-only QR pairing panel, reject bundles without the fingerprint, and
> restore the pinned identity from encrypted paired credentials. The Hub also
> keeps a bounded, hash-chained paired-mode operator audit for pairing,
> WebSocket, and MCP control-plane events. Physical Moto G PHONE and MAC
> localhost smoke now verify the home shell, `phone.battery.status`, and
> `mac.system_info` over USB `adb reverse`; physical Moto G LiteRT-LM
> benchmarking now proves Qwen3 0.6B mixed INT4 can run on CPU, and the
> developer-controlled adapter smoke proves real generated text reaches the
> deterministic quality gate. The model is not runtime-enabled because its
> constrained-label output is still too verbose, and the adapter correctly
> rejects it as non-authoritative instead of wiring it into executable routing.
> The app now exposes a fail-closed local-model runtime gate/status rail with
> at-use model-file rechecks. An optional `modelDebug` LiteRT-LM provider compiles
> behind that async gate, and `modelDebug` has a foreground enable/disable
> setting backed by verified app-private settings. Physical Moto G `modelDebug`
> smoke now verifies that a user-enabled Qwen3 0.6B observe-only pass for an
> unsupported command records a non-executable failed timeline result with
> bounded battery, memory, UI, and logcat artifacts.
> Default GOFFY LITE still does not ship or load the LiteRT-LM runtime. Automatic
> rotation scheduling, Android retrieval for Hub audit, certificate-backed Hub
> identity proof, trusted LAN operation, bootloader unlock eligibility, stock
> restore image capture, and first GSI/DSU boot remain open.

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
- Disabled-by-default local-model intent fallback boundary for unsupported
  commands, with deterministic routes still authoritative
- Fail-closed local-model runtime gate with at-use rechecks and visible status
  rail; no model loads in GOFFY LITE
- Optional `modelDebug` LiteRT-LM provider compile path behind the async
  observe-only gate; default `debug` and `release` stay runtime-free
- Foreground `modelDebug` local-model runtime setting control with app-private
  commit/read-back verification and bounded unsupported-command observation;
  executable model fallback remains disabled and the physical Moto G smoke
  verifies the non-executable timeline path
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
- QR-ready `goffy.pairing.bundle.v2` payloads for USB-loopback onboarding
- Local operator script that writes a short-lived pairing-bundle SVG QR artifact
- In-process pairing smoke verifier for bundle creation, one-time redemption,
  replay rejection, and token rotation
- Loopback paired-token rotation API with old-token invalidation and live-session
  termination
- Loopback-admin Hub identity fingerprint endpoint backed by an owner-only local
  identity file
- Android-pinned USB-loopback Hub identity fingerprint in the pairing bundle and
  encrypted paired credential record
- Foreground Android challenge redemption with API-26 Keystore AES-GCM storage,
  verified restart restore, paired self-revocation, and manual paired-token
  rotation
- Foreground-only Android QR scanner for pairing bundles, with no image storage
  or automatic pairing after scan
- Bounded, loopback-admin Hub operator audit event retrieval for pairing,
  WebSocket, and MCP control-plane activity
- Persistent, hash-chained paired-mode Hub operator audit storage with integrity
  reporting
- Allowlisted, read-only `SAFE mac.system_info` tool
- Strict Kotlin codec plus typed Python protocol models
- Shared typed execution events with separate result, verified, and unverified states
- Shared fixture `protocol/fixtures/mac-system-info-flow.jsonl`
- Shared PHONE capability snapshot `shared/fixtures/phone-tool-capabilities.json`
- Unit, integration, type, lint, and security checks

The previous browser concept is preserved in [`prototype/web-shell`](prototype/web-shell).
The local phone model feasibility note is in
[`docs/architecture/local-model.md`](docs/architecture/local-model.md).
The ROM-first feasibility track is in [`ROM_FEASIBILITY.md`](ROM_FEASIBILITY.md).

## Repository map

```text
android/       Android app and future phone-local capabilities
hub/           FastAPI Hub, auth boundary, routing, audit, and tools
mcp-servers/   MCP server module placeholders
protocol/      Versioned schemas and shared Python protocol package
shared/        Cross-component constants and fixtures
rom/           Future AOSP/GSI integration descriptors and ROM-side checks
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
is still unsupported. Android can now redeem the versioned pairing bundle through
the foreground Hub card over USB loopback, scan that bundle as a QR code, pin the
public Hub fingerprint from the bundle only after the redemption response returns
the same identity, and restore the encrypted credential and fingerprint after
restart. Hub-side token rotation is available over loopback, and Android exposes
a confirmed manual rotation action for paired links.
Generate the local QR artifact from the Mac with:

```bash
GOFFY_HUB_TOKEN='replace-with-the-same-bootstrap-token' \
  .venv/bin/python scripts/create_pairing_qr.py --output goffy-pairing-bundle.svg --force
```

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
python3 scripts/android_preflight.py
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease --no-daemon
python3 scripts/verify_android_apk_budget.py
./android/gradlew -p android :app:compileModelDebugKotlin --no-daemon
python3 scripts/security_scan.py --require-merged-manifests
```

Run the preflight first. It checks JDK 17+, Android SDK Platform 36, Build Tools
36.0.0, `adb`, and the pinned Gradle wrapper before Gradle starts.

See [Android setup](docs/setup/android.md) for the USB localhost debug flow.
The physical Moto G PHONE and MAC localhost smoke paths are verified.

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
`Rotate token` is also paired-only and foreground-confirmed. It cancels active
work, asks the Hub once to rotate the credential, and activates the new bearer
only after encrypted read-back verification. Ambiguous rotation or storage
failure disables Mac access and requires re-pairing.
The Hub keeps a bounded operator audit for pairing, WebSocket, and MCP
control-plane events. In paired mode, events persist to owner-only
`operator-audit.sqlite3` beside the credential store and carry a hash chain with
`previousHash`, `eventHash`, and integrity reporting. It exposes newest-first
events only to loopback bootstrap administrators at `GET /admin/v1/audit/events`
and returns no-store responses. The audit stores closed metadata such as source,
action, outcome, principal kind, credential ID, and bounded detail codes. It does
not store tokens, pairing tokens, request bodies, command text, tool outputs, or
free-form summaries. The DB-local chain tip catches simple tail truncation, but
it does not protect against full database rollback or coordinated rewrite by a
local operator with filesystem access. Android-side retrieval, export, deletion,
and full forensic policy remain future work.
The QR scanner exists only in the visible pairing setup panel, requests the
normal Android `CAMERA` permission from that action, decodes QR codes only, saves
no frame, and only fills the existing pairing-bundle field. The user still has to
tap `Pair phone` before redemption.

GOFFY is now ROM-first. The Android app layer is still useful because it lets us
validate agent policy, Hub pairing, audit, local tools, and model behavior before
flashing anything. It is not the final product if the Moto `kansas` hardware can
be unlocked and boot a recoverable GSI or custom ROM safely.

## Verify the repository

```bash
.venv/bin/python scripts/verify_all.py
```

This runs formatting, linting, type checks, Python tests, package build,
security scan, pairing smoke verification, Android environment preflight, and
Android Gradle plus the GOFFY LITE release APK budget/payload guard, default
debug/release LiteRT-LM dependency guard, optional LiteRT-LM provider compile
gate, and merged-manifest security validation when the local JDK/SDK/adb
prerequisites are present.
Use `--allow-missing-android` only when you intentionally want the Python/Hub
checks to pass while Android Gradle remains blocked by local tooling.

The APK guard fails if `android/app/build/outputs/apk/release/app-release-unsigned.apk`
is missing after the release build, exceeds the current 32 MiB GOFFY LITE budget,
contains LiteRT-LM/model APK entries such as `liblitertlm` or `.litertlm`
assets, or lists LiteRT-LM in the normal debug or release runtime dependency
graph. This keeps small-model work from silently regressing the default Moto
builds.

If verification is blocked by local setup, run the read-only setup doctor:

```bash
.venv/bin/python scripts/setup_doctor.py
.venv/bin/python scripts/setup_doctor.py --json
.venv/bin/python scripts/setup_doctor.py --include-device
```

The doctor redacts repo, home, and absolute toolchain paths, but review output
before posting it to a public issue.

Android CI keeps preflight, Gradle, GOFFY LITE APK budget, optional `modelDebug`
provider compilation, and merged-manifest validation as blocking gates. The
provider compile gate runs after the normal Android build and APK boundary pass,
so failures earlier in the Android sequence are fixed before provider health is
evaluated. If any Android gate fails, CI also runs the setup doctor with
`--android-only --include-device --json` as a non-blocking diagnostic step so the
failure log contains focused, redacted Android toolchain, `adb`, and USB reverse
readiness details.

Before a Moto G physical validation pass, run the readiness verifier:

```bash
.venv/bin/python scripts/verify_moto_g_readiness.py
.venv/bin/python scripts/verify_moto_g_readiness.py --json
.venv/bin/python scripts/guide_moto_g_validation.py
.venv/bin/python scripts/guide_moto_g_validation.py --json
.venv/bin/python scripts/run_moto_g_validation_pipeline.py
.venv/bin/python scripts/run_moto_g_validation_pipeline.py --json
.venv/bin/python scripts/collect_moto_g_validation_bundle.py
.venv/bin/python scripts/collect_moto_g_validation_bundle.py --json
.venv/bin/python scripts/verify_moto_g_validation_bundle.py .goffy-validation/<bundle>
.venv/bin/python scripts/verify_moto_g_validation_bundle.py .goffy-validation/<bundle> --json
```

It reuses the Android/device setup checks, probes only the fixed localhost Hub
health endpoint, and confirms a debug APK is present. It does not configure
`adb reverse`, install an APK, start the Hub, or prove the manual phone checklist.
The guide wraps those read-only checks with the USB setup state, manual checklist
state, and the next safe action to take. It does not execute the USB setup
command or control the phone UI. The bundle collector writes local
`.goffy-validation/moto-g-...` artifacts with guide, smoke, and manifest JSON/text
plus SHA-256 hashes for evidence artifacts. It is read-only for the phone and
refuses to overwrite a timestamped bundle unless `--force` is passed against a
previously marked GOFFY validation bundle directory. The bundle verifier checks
manifest schema, safe relative paths, artifact hashes, metadata marker presence,
and guide/smoke consistency without touching the phone. Verifier exit codes are:
`0` for integrity-valid passed physical smoke evidence, `1` for integrity-valid
but incomplete physical smoke evidence, and `2` for schema or integrity failure.
The pipeline command is the preferred operator path because it collects and
verifies the bundle in one local, phone-read-only step. It still re-runs the same
fixed readiness probes inherited from the collector/recorder path:
`GET http://127.0.0.1:8787/health`, `adb devices -l`, and `adb reverse --list`.
It does not run `adb shell`, configure `adb reverse`, install the APK, or broaden
network access beyond localhost. Pipeline exit code `2` can also mean collection
failed before verification, such as an existing bundle or unsafe `--force`
target.

To prepare the USB path when the only remaining readiness blocker is Hub USB
reverse, use the Moto G USB setup runner. It is plan-only by default:

```bash
.venv/bin/python scripts/run_moto_g_usb_setup.py
.venv/bin/python scripts/run_moto_g_usb_setup.py --json
```

The runner mutates phone state only with both `--execute` and
`--confirm-device-mutation`. That mode runs only fixed `adb reverse tcp:8787
tcp:8787` and `adb install -r .../app-debug.apk` commands after readiness gates
pass. It verifies the reverse before installing the APK. It does not run
`adb shell`, launch GOFFY, enter commands, or bypass the manual phone checklist.
Mutating mode uses only the Android SDK `platform-tools/adb` resolved from the
configured SDK root and only installs the debug APK from this checked-out GOFFY
repository. PATH `adb` and alternate `--repo-root` values are plan-only.

To run the bounded real-device smoke automation after the APK is built and the
Moto G is connected, inspect the plan first:

```bash
.venv/bin/python scripts/run_moto_g_device_smoke.py
.venv/bin/python scripts/run_moto_g_device_smoke.py --json
```

Mutating mode requires the same explicit confirmation pattern:

```bash
.venv/bin/python scripts/run_moto_g_device_smoke.py --execute --confirm-device-mutation
```

That flow first requires exactly one authorized Moto G target, or an explicit
`--device-serial` when multiple devices are connected, and then pins every ADB
call with `-s <device-serial>`. It configures `adb reverse tcp:8787 tcp:8787`,
installs the debug APK, force-stops and launches GOFFY, collapses the Hub setup
card if needed, types only the fixed `check my battery level` smoke command,
verifies that a fresh PHONE task card appeared with expected markers, captures a
screenshot, and saves bounded GOFFY process logcat under
`.goffy-validation/device-smoke/`. Add `--include-mac` only when the Hub is
already running and the phone's saved Hub link is valid, or pass a short-lived
local debug token file under `.goffy-validation`:

```bash
.venv/bin/python scripts/run_moto_g_device_smoke.py \
  --execute \
  --confirm-device-mutation \
  --include-mac \
  --debug-hub-token-file .goffy-validation/runtime/dev-hub-token
```

The MAC path configures only the fixed localhost debug link when a token file is
provided, types only `check my Mac status`, and verifies a fresh visible
`mac.system_info` task card. The token file contains the real raw bearer token;
for ADB-safe entry it must be one line, 24..120 characters, using only
`A-Z`, `a-z`, `0-9`, `.`, `_`, or `-`. Rendered reports and saved debug-link
artifacts redact the token. The script does not clear app data, tap
`Forget link`, start the Hub, accept custom execute commands, print the debug
token, or broaden network access beyond USB loopback.

After the manual phone pass, record redacted evidence:

```bash
.venv/bin/python scripts/record_moto_g_smoke.py \
  --app-launched pass \
  --command-submitted pass \
  --mac-status-displayed pass \
  --timeline-recorded pass \
  --restart-restored pass \
  --json
```

The recorder is read-only. It captures readiness, USB setup status, debug APK
hash, and operator-entered checklist results. It runs only fixed readiness probes
plus read-only `adb devices -l` and `adb reverse --list` through the SDK
`platform-tools/adb`. It never runs `adb shell`, never mutates the phone, never
launches GOFFY, never performs UI automation, never executes arbitrary commands,
and never accepts free-form notes.

To package the final evidence after the manual phone pass:

```bash
.venv/bin/python scripts/run_moto_g_validation_pipeline.py \
  --app-launched pass \
  --command-submitted pass \
  --mac-status-displayed pass \
  --timeline-recorded pass \
  --restart-restored pass
```

Read [SECURITY.md](SECURITY.md) before exposing the Hub beyond localhost.
