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

## Milestones 3-8

3. MCP capability registry and standards-compliant MCP servers
4. Foreground-only voice, camera, QR, and OCR
5. Narrow, approval-gated Mac automation
6. Inspectable and deletable user-approved memory
7. Polished, accessible, battery-aware GOFFY UI
8. Signed beta, packaged Hub, diagnostics, upgrade, and rollback
