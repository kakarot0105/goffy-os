# GOFFY OS

GOFFY OS is an open-source, ROM-first agentic operating system project for
repurposing an older Android phone into a dedicated Jarvis-like device. The
short-term Android app remains a bootstrap, validation, and fallback layer; the
target product is a GOFFY-controlled Android ROM or GSI-derived system image
when the exact Moto hardware can support it safely. A macOS Hub provides
controlled access to heavier local capabilities. MCP-compatible typed tools are
the capability boundary.

> Status: ROM feasibility plus Milestone 3 MCP core in progress. The current
> repo now treats ROM/GSI feasibility for the exact Moto G 2025 `kansas`
> / `XT2513V` target as the primary product track, with the launcher/app layer
> kept for safe validation and fallback. The current repo implements offline
> PHONE actions, exact-ID user-approved local PHONE memory controls,
> discovery-gated SAFE Mac status/process/file-list actions, read-only GOFFY ROM
> status, an
> approved-repo SAFE Git status MCP tool, an opt-in SAFE Mac clipboard-read MCP
> tool, an official MCP
> Streamable HTTP boundary, stable Hub paired-device credentials, Keystore-backed
> Android pairing restore, and a persistent user-visible Android audit trail
> for the newest 50 terminal tasks. MCP tool-list changes now stream with
> bounded, session-local reconnect replay. Paired phones can now forget locally,
> ask the Hub once to revoke or rotate the exact matching credential over
> loopback, and register an Android approval signing public key during pairing.
> The Hub now emits a versioned USB-loopback pairing bundle with its
> public loopback identity fingerprint, and Android can scan that bundle through
> a foreground-only QR pairing panel, reject bundles without the fingerprint, and
> restore the pinned identity from encrypted paired credentials. The Hub also
> keeps a bounded, hash-chained paired-mode operator audit for pairing,
> WebSocket, and MCP control-plane events, and exposes an explicit
> USB-loopback-only Hub identity trust contract that blocks certificate,
> public-key, and LAN trust claims until those are actually implemented.
> Android paired links now track the current bearer issue time and show a
> foreground token-rotation reminder when the bearer ages past local policy; no
> background rotation is performed. CONFIRM Mac WebSocket execution is now
> device-bound: paired Android approval responses are signed with the phone
> approval key and verified by the Hub before `mac.apps.open` can run.
> Physical Moto G PHONE and MAC
> localhost smoke now verify the home shell, `phone.battery.status`,
> approved `phone.memory.remember`, `phone.memory.list`, and `mac.system_info`
> over USB `adb reverse`; physical Moto G LiteRT-LM
> benchmarking now proves Qwen3 0.6B mixed INT4 can run on CPU, and the
> developer-controlled adapter smoke proves real generated text reaches the
> deterministic quality gate. The model is not runtime-enabled because its
> constrained-label output is still too verbose, and the adapter correctly
> rejects it as non-authoritative instead of wiring it into executable routing.
> The app now exposes a fail-closed local-model runtime gate/status rail with
> at-use model-file rechecks. An optional `modelDebug` LiteRT-LM provider compiles
> behind that async gate, and `modelDebug` has a foreground enable/disable
> setting backed by verified app-private settings. Physical Moto G `modelDebug`
> smoke now verifies that user-enabled Qwen3 0.6B and Granite 350M observe-only
> passes for an unsupported command record non-executable failed timeline
> results with bounded battery, memory, UI, and logcat artifacts. Three Granite
> 350M repeated runs completed safely, but production local-model acceptance is
> still blocked by 21.7-22.7 second observation latency and about 175 MB idle
> PSS after 60 seconds. The acceptance verifier now reports rejected-run
> elapsed/PSS/battery/model evidence as structured JSON while keeping the
> production budgets unchanged. The next local-model path is now a
> verifier-backed reuse-first lightweight intent-classifier registry, with
> TensorFlow Lite Task Text selected only as a modelDebug prototype candidate.
> Its pinned dependency now resolves and builds in an isolated Android probe, and
> `modelDebug` now compiles a Task Text classifier bridge plus a variant-scoped
> Moto benchmark harness. The seed PHONE/MAC/CLOUD/UNKNOWN router corpus and
> routing-quality evidence verifier are now in-repo, the Model Maker training
> package generator plus audited-image Docker runner contract cover export of a
> tiny metadata-backed `.tflite` candidate, and the eval-suite runner collected
> all 16 physical Moto artifacts for the first manually exported model.
> Classifier acceptance remains blocked because that tiny model failed the
> routing-quality gate, so it stays benchmark-only and non-authoritative.
> Default GOFFY LITE still does not ship or load the LiteRT-LM runtime. Automatic
> rotation scheduling, Android retrieval for Hub audit, certificate-backed Hub
> identity proof, trusted LAN operation, bootloader unlock eligibility, stock
> restore image capture, and first GSI/DSU boot remain open.

## Current vertical slice

- Kotlin/Jetpack Compose GOFFY LITE home shell
- ROM system-app home-surface contract requiring GOFFY to remain user-selectable
  as Android HOME without privileged or platform-signed authority
- User-visible HOME-shell setup card that verifies GOFFY default-home status via
  the audited `phone.device.info` route and opens trusted Android Home/default
  app settings for manual user selection
- Deterministic route for exact `Show/Check [me] my Mac status`
- Offline deterministic route for battery status commands
- Permission-free, allowlisted `SAFE phone.battery.status` execution
- Privacy-minimized, offline `SAFE phone.device.info` execution
- Approval-gated `CONFIRM phone.note.create` with app-private SQLite persistence
- Approval-gated `CONFIRM phone.memory.remember`, `phone.memory.update`,
  `phone.memory.forget`, bounded `SAFE phone.memory.list`, and approval-gated
  destructive `CONFIRM phone.memory.forget_all` in app-private SQLite with
  inspectable provenance
- Opt-in physical Moto G smoke coverage for approved local-memory write/list
  without deleting existing phone memories
- Approval-gated `CONFIRM phone.timer.create` through an allowlisted system Clock
- Approval-gated `CONFIRM phone.flashlight.set` with CameraManager callback verification
- Immutable, bounded PHONE capability registry with MCP-shaped closed schemas
- Exact-task, exact-arguments, expiring, single-use phone approval grants
- Disabled-by-default local-model intent fallback boundary for unsupported
  commands, with deterministic routes still authoritative
- Zero-dependency GOFFY LITE micro intent fallback for bounded unsupported
  commands; it suggests PHONE, MAC, or CLOUD as a non-executable timeline hint
- Fail-closed local-model runtime gate with at-use rechecks and visible status
  rail; no model loads in GOFFY LITE
- Optional `modelDebug` LiteRT-LM provider compile path behind the async
  observe-only gate; default `debug` and `release` stay runtime-free
- Foreground `modelDebug` local-model runtime setting control with app-private
  commit/read-back verification and bounded unsupported-command observation;
  executable model fallback remains disabled and the physical Moto G smoke
  verifies the non-executable timeline path
- Reuse-first local intent-classifier candidate registry and verifier for the
  next smaller on-phone model path; no classifier dependency or model asset is
  included in default GOFFY LITE builds
- Optional TensorFlow Lite Task Text dependency probe for the classifier path;
  the pinned dependency builds in isolation and the `modelDebug` classifier
  bridge/benchmark harness compiles without adding a default runtime dependency
- Seed local intent-router corpus plus an opt-in routing-quality verifier for
  physical Moto Task Text benchmark evidence
- Eval-suite runner that reuses the single-command Moto benchmark harness and
  writes a routing-quality evidence manifest after one suite-level setup; still
  requires a real tiny model
- Model Maker training-package generator for the verified local intent-router
  corpus; writes CSVs, labels, source-policy manifest, and an isolated optional
  training script without adding TensorFlow to the repo venv
- Training-environment preflight for the generated package, Python 3.9/3.10
  compatibility, optional pip dry-run, and Docker fallback visibility
- Bounded, fail-closed Docker Model Maker export runner contract that requires
  an audited immutable image before execution, plus physical Moto eval-suite
  evidence showing the first tiny Task Text candidate loads but fails the
  routing-quality gate
- Reuse-first Task Text export-image audit evidence generator that consumes
  Trivy or Grype JSON and blocks critical, high, or medium findings
- Read-only `SAFE goffy.rom.status` Hub/MCP tool plus Android routes for
  `Show GOFFY ROM status` and `What are we building now?`
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
- QR-ready `goffy.pairing.bundle.v3` payloads for USB-loopback onboarding
- Local operator script that writes a short-lived pairing-bundle SVG QR artifact
- In-process pairing smoke verifier for bundle creation, one-time redemption,
  replay rejection, and token rotation
- Loopback paired-token rotation API with old-token invalidation and live-session
  termination
- Loopback-admin Hub identity fingerprint endpoint backed by an owner-only local
  identity file
- Public Hub identity trust contract declaring loopback-only proof,
  absent public-key/certificate pins, and no trusted LAN support
- Android-pinned USB-loopback Hub identity fingerprint in the pairing bundle and
  encrypted paired credential record
- Foreground Android challenge redemption with API-26 Keystore AES-GCM storage,
  verified restart restore, paired self-revocation, and manual paired-token
  rotation
- Foreground paired-token rotation reminder based on the current bearer issue
  time; reminders do not rotate automatically or schedule background work
- Foreground-only Android QR scanner for pairing bundles, with no image storage
  or automatic pairing after scan
- Bounded, loopback-admin Hub operator audit event retrieval for pairing,
  WebSocket, and MCP control-plane activity
- Persistent, hash-chained paired-mode Hub operator audit storage with integrity
  reporting
- Allowlisted, read-only `SAFE mac.system_info` tool
- Default read-only `SAFE goffy.rom.status` tool for bounded ROM-0 readiness
  status from fixed local GOFFY validation artifacts; it exposes no artifact
  paths and grants no unlock, reboot, flash, erase, wipe, boot, or shell
  authority
- macOS-gated, allowlisted, read-only `SAFE mac.processes.list` tool for bounded running
  process metadata, including an Android `What's running on my Mac` route that
  does not request command lines, executable paths, environment variables, open
  files, or network data
- Optional `SAFE mac.files.list` and `SAFE mac.files.largest` tools for
  explicitly configured Mac file roots, including Android routes for listing
  and finding largest files in the default approved root
- Optional `SAFE git.status` Hub/MCP tool for explicitly configured Git worktree roots,
  including an Android `Show my git status` route for the default approved repo
- Optional, disabled-by-default `SAFE mac.clipboard.read` Hub/MCP tool for
  bounded plaintext reads from the Mac clipboard, including an Android
  `Read my Mac clipboard` route that does not read clipboard text aloud
- Optional `SAFE mac.apps.list` Hub/MCP tool for configured app-catalog reads,
  including an Android `List my Mac apps` route that cannot launch apps
- Optional `CONFIRM mac.apps.open` Hub WebSocket tool for approved app
  launching; Android approval responses are signed with the paired phone
  approval key and Hub-verified before execution
- Strict Kotlin codec plus typed Python protocol models
- Shared typed execution events with separate result, verified, and unverified states
- Shared fixture `protocol/fixtures/mac-system-info-flow.jsonl`
- Shared PHONE capability snapshot `shared/fixtures/phone-tool-capabilities.json`
- Unit, integration, type, lint, and security checks

The previous browser concept is preserved in [`prototype/web-shell`](prototype/web-shell).
The local phone model feasibility note is in
[`docs/architecture/local-model.md`](docs/architecture/local-model.md).
The Jarvis-style home/ROM UX contract is in
[`docs/architecture/goffy-os-design.md`](docs/architecture/goffy-os-design.md).
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
the same identity, reject bundles that claim certificate, public-key, or LAN
trust, and restore the encrypted credential and fingerprint after restart.
Hub-side token rotation is available over loopback, and Android exposes a
confirmed manual rotation action plus a foreground stale-token reminder for
paired links.
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

Default Mac process listing requires no extra configuration on macOS Hub hosts.
Non-macOS hosts do not register the tool. The Hub exposes `SAFE
mac.processes.list` with bounded process count, PID, process-name basename,
status, RSS memory, and optional start-time metadata. It uses `psutil` directly,
never invokes a shell, never returns command lines, executable paths, environment
variables, open files, network connections, or user names, and Android can invoke
it with `What's running on my Mac`, `What is running on my Mac`,
`Show my Mac processes`, `List my Mac processes`, or
`Check me my Mac processes`. TTS reports only counts, not process names.

Optional file listing is disabled until approved roots are configured:

```bash
export GOFFY_MAC_FILES_ROOTS="$HOME/Documents/GitHub"
```

When set, the Hub exposes `SAFE mac.files.list` and `SAFE mac.files.largest`.
Both use root index and relative path only, hide dotfiles by default, never
follow symlink targets, never read file contents, and never expose absolute root
paths in tool output. Android can invoke the default approved root with
`List my Mac files`, `Show my Mac files`, or
`Find the largest files on my Mac`; richer root/path selection remains future
work.

Optional Git status is disabled until approved repositories are configured:

```bash
export GOFFY_GIT_REPO_ROOTS="$HOME/Documents/GitHub/goffy-os"
```

When set, the Hub exposes `SAFE git.status` over MCP. It reads bounded repository
status metadata by repo index only, never accepts command text or repo paths from
clients, never returns absolute repo roots or file contents, and never fetches,
commits, pushes, or runs tests. Android can invoke the default approved repo with
`Show my git status` or `Check my git status`; richer repo selection remains
future work.

Optional clipboard reading is disabled until the operator installs the optional
macOS provider and enables the exact feature flag:

```bash
.venv/bin/pip install -e '.[clipboard]'
export GOFFY_MAC_CLIPBOARD_READ_ENABLED=true
```

When set, the Hub exposes `SAFE mac.clipboard.read` over MCP. It returns bounded
plaintext only, never writes the clipboard, never polls in the background, never
reads clipboard content during health checks, and does not expose binary
clipboard formats or file URLs. Plaintext containing `file://` is rejected as
unsupported without returning text. Android can invoke this exact tool with
`Read my Mac clipboard` or `Show my Mac clipboard`; TTS reports status without
reading clipboard contents aloud.

To expose a safe Mac app catalog:

```bash
export GOFFY_MAC_APP_ALLOWLIST='Safari=com.apple.Safari,Terminal=com.apple.Terminal'
```

When set, the Hub exposes `SAFE mac.apps.list` over MCP. The tool returns only
configured display names and bundle identifiers. It does not scan
`/Applications`, reveal app paths, launch apps, or open files. Android can
invoke it with `List my Mac apps`, `Show my Mac applications`, or
`What apps are approved on my Mac?`.

To enable approval-gated app launching for that same allowlist:

```bash
export GOFFY_MAC_APP_OPEN_ENABLED=true
```

When enabled, the Hub registers `CONFIRM mac.apps.open` internally, and Android
can prepare the typed route plus visible approval prompt for commands like
`Open Safari on my Mac`. The authenticated WebSocket endpoint exposes and
executes the CONFIRM tool only for paired credentials that registered an Android
approval public key during pairing. Android signs the Hub-issued
`goffy.approval.v1` response payload with its Keystore approval key, and the Hub
verifies the signature, credential ID, exact task, exact tool, canonical
argument hash, issue time, and expiry before launching the app. Bootstrap/dev
tokens and paired credentials without an approval key still discover SAFE tools
only. The MCP endpoint remains SAFE-only.

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

For the next ROM-0 evidence step, refresh the read-only probe and safe manual
action packet in one command. It tells the human exactly which restore/unlock,
fastboot, and official GSI candidate evidence is missing without emitting
unlock, flash, erase, or reboot commands:

```bash
.venv/bin/python scripts/refresh_rom0_action_packet.py
```

This writes `.goffy-validation/rom-feasibility-current.json`,
`.goffy-validation/rom-0-manual-action-packet.md`,
`.goffy-validation/rom-0-manual-action-packet.json`, and
`.goffy-validation/rom-bootloader-visibility-guide.md`,
`.goffy-validation/rom-bootloader-visibility-guide.json`, and
`.goffy-validation/rom-0-operator-checklist.md`,
`.goffy-validation/rom-0-operator-checklist.json`, and
`.goffy-validation/rom-0-refresh-report.json`. It consumes existing evidence
files only when they validate cleanly; invalid evidence fails closed in the
refresh report. A blocked ROM state returns a blocked report instead of top-level
success even when the refresh artifacts were written correctly.

The refresh command also writes the ordered operator checklist. To regenerate
only that checklist from the latest refresh report, run:

```bash
.venv/bin/python scripts/create_rom0_operator_checklist.py
```

The checklist keeps destructive actions withheld, orders the remaining human
gates, and flags stock restore evidence as mandatory before unlock, DSU, flash,
or boot decisions can advance.

Then generate a local manual-gates template before editing evidence by hand:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --unlock-eligibility-evidence .goffy-validation/rom-unlock-eligibility-evidence.json \
  --stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json \
  --output .goffy-validation/rom-0-manual-gates.json
```

Both files stay under `.goffy-validation`, default to blocked values, and do not
authorize unlock, flash, erase, root, or boot-image changes.

The refresh command generates the manual bootloader visibility guide as part of
the packet. To regenerate only that guide, run:

```bash
.venv/bin/python scripts/create_rom_bootloader_visibility_guide.py
```

The guide explains the physical-phone bootloader step and still blocks ROM
readiness until visibility is actually recorded.

To record host fastboot readiness without changing phone state:

```bash
.venv/bin/python scripts/create_rom_fastboot_evidence.py
```

If the human later manually enters bootloader mode, use only the read-only
visibility check:

```bash
.venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check
```

This records redacted fastboot evidence only. It never reboots the phone and
never emits unlock, flash, erase, wipe, boot, or reboot commands.

Include that evidence in the ROM-0 readiness report:

```bash
.venv/bin/python scripts/verify_rom0_readiness.py \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --manual-gates-json .goffy-validation/rom-0-manual-gates.json \
  --fastboot-evidence-json .goffy-validation/rom-fastboot-evidence.json \
  --gsi-candidate-evidence-json .goffy-validation/rom-gsi-candidate-evidence.json \
  --signing-plan-json .goffy-validation/rom-signing/release-signing-plan.json \
  --apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json \
  --signed-apk .goffy-validation/rom-signing/GoffyOS-signed.apk \
  --evidence-root .
```

To record candidate integrity for the first official Google ARM64 GSI, first
review Google's official GSI terms yourself. Only after personally accepting
those terms, download the archive manually outside this repo, copy the SHA-256
from Google's GSI release page, then run the offline verifier:

```bash
.venv/bin/python scripts/create_rom_gsi_candidate_evidence.py \
  --artifact /absolute/path/outside/repo/aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip \
  --source-url https://developer.android.com/topic/generic-system-image/releases \
  --download-url https://dl.google.com/developers/android/baklava/images/gsi/aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip \
  --expected-sha256 2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea \
  --candidate-name "Official Google Android 16 ARM64 GSI" \
  --android-release 16 \
  --architecture arm64 \
  --output .goffy-validation/rom-gsi-candidate-evidence.json
```

This creates redacted evidence only; it does not download, install, unlock,
flash, reboot, or authorize DSU use.

For ROM APK packaging, keep release keys outside the repo, generate a dry-run
signing plan before producing any `GoffyOS-signed.apk`, then verify the signed
artifact after the human-run signing command succeeds:

```bash
.venv/bin/python scripts/create_rom_release_signing_plan.py \
  --keystore /absolute/path/outside/repo/goffy-release.jks
.venv/bin/python scripts/verify_rom_release_apk.py \
  --apk .goffy-validation/rom-signing/GoffyOS-signed.apk
```

The plan uses Android SDK `apksigner`, records only password environment
variable names, and does not sign, flash, unlock, or mutate an AOSP checkout.
The APK verifier records hash, size, and v2/v3 signature evidence for an
already signed artifact only.

## Verify the repository

```bash
.venv/bin/python scripts/verify_all.py
```

This runs formatting, linting, type checks, Python tests, package build,
security scan, pairing smoke verification, Android environment preflight, and
Android Gradle plus the local intent-router corpus guard, GOFFY LITE release APK
budget/payload guard, default debug/release LiteRT-LM dependency guard,
TensorFlow Lite Task Text dependency guard, optional LiteRT-LM provider compile
gate, optional `modelDebug` Task Text classifier compile/package gate, and
merged-manifest security validation when the local JDK/SDK/adb prerequisites are
present.
Use `--allow-missing-android` only when you intentionally want the Python/Hub
checks to pass while Android Gradle remains blocked by local tooling.

The APK guard fails if `android/app/build/outputs/apk/release/app-release-unsigned.apk`
is missing after the release build, exceeds the current 32 MiB GOFFY LITE budget,
contains local-model APK entries such as `liblitertlm`, `libtask_text_jni.so`,
`.litertlm`, or GOFFY local-model `.tflite` assets, or lists LiteRT-LM /
TensorFlow Lite Task Text in the normal debug or release runtime dependency
graph. It also checks the default `debugAndroidTest` APK for Task Text JNI
payloads so benchmark-only dependencies stay out of broad instrumentation
artifacts. This keeps small-model work from silently regressing the default Moto
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
provider compilation, `modelDebug` Task Text classifier packaging, and
merged-manifest validation as blocking gates. The provider/classifier compile
gates run after the normal Android build and APK boundary pass; if the APK
budget fails, the verifier still runs the later gates for diagnostic coverage so
one report shows all Android boundary failures.
If any Android gate fails, CI also runs the setup doctor with
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
card if needed, verifies the launch-visible HOME shell, connection, target, HOME
setup card, and device-map entry from `after-launch.xml` into `home-surface.xml`,
uses one bounded scroll to capture and verify device-map node labels in
`device-map.xml`, types only the fixed `check my battery level` smoke command,
verifies that a fresh PHONE task card appeared with expected markers, captures a
screenshot, and saves bounded GOFFY process logcat under
`.goffy-validation/device-smoke/`. Add `--include-memory` to also submit a
unique per-run `remember that goffy memory smoke ...` command, tap the matching
`Approve once` control inside that fresh task card, verify
`phone.memory.remember`, then submit `what do you remember` and verify the
unique `goffy memory smoke ...` text is listed in the fresh memory-list result.
The memory smoke does not run `forget all memories`, so it will not delete
existing local GOFFY memories.

Per-memory command controls are also available from the phone timeline:
`update memory #1 to updated local memory` updates one exact app-private memory
after approval, and `delete memory #1` deletes one exact app-private memory
after approval. GOFFY verifies each mutation before reporting success and keeps
memory text out of persistent terminal audit records.

Add `--include-mac` only when the Hub is already running and the phone's saved
Hub link is valid. To exercise the production-like paired path, require GOFFY
to restore the paired Hub link after the forced app restart before any MAC
command is typed:

```bash
.venv/bin/python scripts/run_moto_g_device_smoke.py \
  --execute \
  --confirm-device-mutation \
  --include-mac \
  --require-paired-hub \
  --mac-command "Show GOFFY ROM status"
```

`--require-paired-hub` is mutually exclusive with `--debug-hub-token-file`. It
does not inject pairing state; it only verifies the visible Hub card shows a
restored paired localhost link before the MAC smoke proceeds.

For legacy USB development smoke, pass a short-lived local debug token file
under `.goffy-validation`:

```bash
.venv/bin/python scripts/run_moto_g_device_smoke.py \
  --execute \
  --confirm-device-mutation \
  --include-mac \
  --debug-hub-token-file .goffy-validation/runtime/dev-hub-token
```

The MAC path configures only the fixed localhost debug link when a token file is
provided, types only an allowlisted MAC smoke command, and verifies a fresh
visible task card. The default is `check my Mac status` for `mac.system_info`;
the process-list route can be smoked with
`--mac-command "What is running on my Mac"` for `mac.processes.list`, or
`--mac-command "Show GOFFY ROM status"` for `goffy.rom.status`. The token
file contains the real raw bearer token; for ADB-safe entry it must be one line,
24..120 characters, using only
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
