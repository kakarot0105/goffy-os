# GOFFY OS Roadmap

## Milestone ROM-0: Moto G ROM feasibility - in progress

- [x] ROM-first product direction documented
- [x] Read-only Moto G ROM feasibility probe
- [x] Exact connected target identified as `kansas_g_sys` / `kansas` / MediaTek `MT6835`
- [x] Treble and dynamic-partition status captured from the physical phone
- [x] Android DSU package and `START_INSTALL` activity captured from the physical phone
- [x] Current locked bootloader state captured from the physical phone
- [x] First GSI/DSU candidate shortlist with license and Moto/MediaTek risk notes
- [x] No-flash planning checklist generator and DSU staging setup guide
- [x] Official stock restore source identified through Motorola Software Fix
- [x] Manual restore/unlock evidence validator and sensitive-key rejection
- [x] Safe ROM-0 manual gate template generator with optional stock-restore merge
- [x] Rollback Markdown template and exact archive/SHA evidence validation
- [x] Local stock-restore archive hashing helper with redacted evidence output
- [x] Non-privileged ROM system-app descriptor and validator
- [x] Safe AOSP product-overlay template and validator for `GoffyOS`
- [x] Dry-run release signing plan for externally keyed ROM APK
- [x] Local signed ROM APK verification evidence generator
- [x] Dry-run-first AOSP product import generator for signed GOFFY APK staging
- [x] Offline ROM-0 readiness reporter for probe, manual gate, and signed APK evidence
- [x] Android Home-shell intent declared, security-scanned, and physically queried
- [ ] Manual OEM-unlocking and Motorola unlock-token eligibility result
- [ ] Exact stock firmware/recovery archive, checksum, and rollback checklist
- [ ] User-approved destructive unlock/flash decision point

## Milestone 0: Foundation - in progress

- [x] Monorepo structure and governance documents
- [x] Android Compose GOFFY LITE shell source
- [x] FastAPI Hub shell and health endpoint
- [x] Versioned protocol models and schemas
- [x] Authenticated WebSocket boundary
- [x] Typed `mac.system_info` registry tool
- [x] Python unit and integration tests
- [x] CI, lint, type, and security configuration
- [x] Exact source and merged Android manifest capability checks
- [x] Android build verified on a configured JDK 17 / SDK 36 toolchain
- [x] Android environment preflight for JDK, SDK, adb, and Gradle wrapper readiness
- [x] Unified local verification runner with Android preflight-gated Gradle
- [x] CI aligned with the unified verifier and Android preflight gate
- [x] Read-only setup doctor for Python and Android toolchain diagnostics
- [x] Optional read-only ADB readiness diagnostics without serial logging
- [x] Redacted Android CI setup diagnostics after failed Android gates
- [x] One-command Moto G readiness verifier for toolchain, USB, Hub, and APK checks
- [x] Explicit-confirmation Moto G USB reverse/install setup runner
- [x] Redacted Moto G physical smoke evidence recorder
- [x] Read-only Moto G physical validation guide
- [x] Local Moto G validation bundle collector
- [x] Offline Moto G validation bundle verifier
- [x] One-command Moto G validation collect-and-verify pipeline
- [x] Bounded fixed-command Moto G device smoke automation
- [x] GOFFY home shell verified on the Moto G physical device
- [x] `phone.device.info` reports GOFFY home/system-app status on the Moto G
- [x] Foreground charging dock mode keeps GOFFY awake without global display changes

## Milestone 1: First end-to-end action - in progress

- [x] Android invocation client with authenticated per-invocation WebSockets
- [x] Deterministic routing for exact `Show/Check [me] my Mac status`
- [x] Strict Kotlin codec with separate `ToolResult` and `VerificationResult`
- [x] Task-state reducer and progress/result/verification timeline rendering
- [x] Shared fixture plus Android/Python failure, retry, and cancellation tests
- [x] Moto G physical localhost debug verification (`adb reverse` flow)

## Milestone 2: Phone engine - in progress

- [x] Permission-free `phone.battery.status` local tool
- [x] Offline deterministic battery-status routing
- [x] Typed PHONE and MAC execution result boundary
- [x] PHONE, MAC, and CLOUD target state
- [x] Privacy-minimized `phone.device.info`
- [x] Foreground-only explicit TextToSpeech readout for latest safe result
- [x] Visible, expiring, exact-task approval lifecycle
- [x] Approval-gated app-private `phone.note.create` with post-write verification
- [x] Approval-gated allowlisted-system `phone.timer.create` dispatch with explicit `UNVERIFIED` state
- [x] API 26 and API 33+ system Clock intent tests
- [x] Approval-gated, callback-verified `phone.flashlight.set`
- [x] Physical Moto G battery-status verification
- [x] Disabled-by-default local-model intent fallback safety boundary
- [x] LiteRT-LM Android dependency compatibility probe before runtime wiring
- [x] Benchmark-only Moto G LiteRT-LM instrumentation harness
- [x] Moto G local-model runtime benchmark for one tiny text model
- [x] Local-model routing quality gate before any runtime fallback wiring
- [x] Disabled generated-text adapter into the local-model quality gate
- [x] Developer-controlled `androidTest` LiteRT-LM adapter smoke on the physical Moto G
- [x] Production fail-closed local-model activation gate with at-use rechecks and visible status rail
- [x] Automated GOFFY LITE release APK size/model-payload guard plus default debug/release LiteRT-LM dependency guard
- [x] Optional `modelDebug` LiteRT-LM provider compile path behind the async activation gate
- [x] Foreground, verified `modelDebug` LiteRT-LM runtime setting control without GOFFY LITE APK-size regression
- [x] User-enabled `modelDebug` LiteRT-LM unsupported-command observation execution as non-executable timeline task
- [x] Automated physical Moto G `modelDebug` observe-only local-model smoke with UI, battery, memory, and logcat evidence
- [x] Read-only repeated-run and idle-cleanup acceptance verifier for `modelDebug`
- [x] Read-only Moto G `modelDebug` idle-cleanup evidence collector
- [ ] Repeated-run responsiveness, idle-unload, and production acceptance evidence for user-enabled LiteRT-LM observation execution

## Milestone 3: MCP core - in progress

- [x] Typed Hub capability registry with bounded, stable discovery metadata
- [x] GOFFY protocol `0.2.0` capability discovery request and response
- [x] MCP `2025-11-25`-aligned tool schemas, annotations, and namespaced metadata
- [x] Android discovery gate before `mac.system_info` invocation
- [x] Per-invocation discovery consumption, bounded timeout, and no post-send replay
- [x] Unified, bounded PHONE capability registry with shared schema fixture
- [x] Official MCP Streamable HTTP initialization, `tools/list`, and registry-backed `tools/call`
- [x] Bounded, fail-closed tool-health checks
- [x] Persistent, user-visible Android audit trail for terminal tasks
- [x] Resumable MCP list-change notifications
- [x] Loopback bootstrap pairing with stable, revocable paired-device credentials
- [x] Foreground Android pairing redemption with Keystore-backed restart restore
- [x] Loopback paired-device self-revocation with verified/unverified phone reporting
- [x] Versioned QR-ready USB-loopback pairing bundle contract
- [x] Local operator QR SVG generation for USB-loopback pairing bundles
- [x] In-process QR bundle redemption smoke verifier
- [x] Foreground Android QR challenge transfer for USB-loopback pairing bundles
- [x] Loopback paired-device token rotation API with old-token invalidation
- [x] Android-triggered paired-token rotation UX and fail-closed recovery policy
- [x] Stable loopback Hub identity fingerprint for future trust onboarding
- [x] Android-pinned USB-loopback Hub identity in QR pairing and Keystore restore
- [x] Bounded loopback-admin Hub/MCP operator audit event retrieval
- [x] Paired loopback Hub/MCP self-audit event retrieval
- [x] Persistent hash-chained Hub/MCP operator audit storage foundation
- [ ] Certificate/public-key trusted Hub identity onboarding
- [ ] Automatic token rotation reminders or schedules after physical validation
- [x] Android retrieval and user controls for Hub/MCP operator audit

## Milestones 4-8

4. Foreground-only voice, camera, QR, and OCR
   - [x] Foreground push-to-talk command capture with immediate lifecycle cleanup
5. Narrow, approval-gated Mac automation
   - [x] Optional approved-root `mac.files.list` Hub/MCP tool
   - [x] Android route, typed codec, timeline, speech, and audit handling for
     default approved-root `mac.files.list`
   - [x] Optional approved-repo `git.status` Hub/MCP tool
   - [x] Android route, typed codec, timeline, speech, and audit handling for
     default approved-repo `git.status`
   - [x] Optional opt-in `mac.clipboard.read` Hub/MCP tool
   - [x] Android route, typed codec, timeline, speech, and audit handling for
     `mac.clipboard.read`
6. Inspectable and deletable user-approved memory
7. Polished, accessible, battery-aware GOFFY UI
8. Signed beta, packaged Hub, diagnostics, upgrade, and rollback
