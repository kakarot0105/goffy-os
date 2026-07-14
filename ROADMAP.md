# GOFFY OS Roadmap

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
- [ ] GOFFY home shell verified on the Moto G physical device

## Milestone 1: First end-to-end action - in progress

- [x] Android invocation client with authenticated per-invocation WebSockets
- [x] Deterministic routing for exact `Show/Check [me] my Mac status`
- [x] Strict Kotlin codec with separate `ToolResult` and `VerificationResult`
- [x] Task-state reducer and progress/result/verification timeline rendering
- [x] Shared fixture plus Android/Python failure, retry, and cancellation tests
- [ ] Moto G physical localhost debug verification (`adb reverse` flow)

## Milestone 2: Phone engine - in progress

- [x] Permission-free `phone.battery.status` local tool
- [x] Offline deterministic battery-status routing
- [x] Typed PHONE and MAC execution result boundary
- [x] PHONE, MAC, and CLOUD target state
- [x] Privacy-minimized `phone.device.info`
- [x] Visible, expiring, exact-task approval lifecycle
- [x] Approval-gated app-private `phone.note.create` with post-write verification
- [x] Approval-gated allowlisted-system `phone.timer.create` dispatch with explicit `UNVERIFIED` state
- [x] API 26 and API 33+ system Clock intent tests
- [x] Approval-gated, callback-verified `phone.flashlight.set`
- [ ] Physical Moto G battery-status verification

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
- [ ] Trusted Hub identity onboarding
- [ ] Automatic token rotation reminders or schedules after physical validation
- [ ] Direct Hub/MCP operator audit after stable paired identity and user-visible retrieval

## Milestones 4-8

4. Foreground-only voice, camera, QR, and OCR
5. Narrow, approval-gated Mac automation
6. Inspectable and deletable user-approved memory
7. Polished, accessible, battery-aware GOFFY UI
8. Signed beta, packaged Hub, diagnostics, upgrade, and rollback
