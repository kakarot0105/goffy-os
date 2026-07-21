# GOFFY OS Design Specification

GOFFY OS should feel like a dedicated agentic phone environment, not a normal
chat app. The near-term product is a default-home Android shell backed by the
secure Mac Hub. The long-term product is the same shell preinstalled into a
recoverable ROM or GSI-derived image after Moto `kansas` feasibility gates pass.

This document is the design contract for Milestone 7 and the ROM home surface.
It does not grant new permissions or execution authority.

## Reuse-First Scan

The design should reuse proven patterns, not blindly import whole apps.

| Source | License signal | Useful pattern | Decision |
| --- | --- | --- | --- |
| `mslalith/focus_launcher` | GPL-3.0 | Minimal Compose launcher with favorites, app hiding, dark UI, and home-screen focus | Reference only. Do not copy code unless GOFFY accepts GPL obligations for the affected module. |
| `android/nowinandroid` | Apache-2.0 | Modern Android architecture, modular Compose UI, tests, and accessibility posture | Safe architecture reference. Prefer patterns over copied code. |
| `google/jetpack-camera-app` | Apache-2.0 | CameraX plus Compose lifecycle, viewfinder, and on-device test posture | Safe camera lifecycle reference for future camera/QR/OCR screens. |
| `alphacep/vosk-api` | Apache-2.0 | Offline speech recognition for Android-scale devices | Candidate for optional offline voice after APK, RAM, latency, and idle cleanup benchmarks. |
| `DicioTeam/dicio-android` | GPL-3.0 | Privacy-first Android assistant with speech and graphical feedback | Reference only. Do not copy code unless license impact is accepted. |
| `VinayByte/mlkit-qr-code-scan-android-kotlin` | License not confirmed in scan | CameraX plus ML Kit QR scanning sample | Do not copy. Prefer official CameraX/ML Kit docs and existing GOFFY scanner code. |

Reuse rule for future feature work:

- Apache-2.0 or permissive code may be adapted only after local dependency,
  permission, binary-size, and security review.
- GPL code may influence UX concepts but must not be copied into the main app
  without an explicit licensing decision.
- Unknown-license snippets are not reusable.
- Any copied source requires an ADR or implementation note with source,
  license, local modifications, and why it is safe on a Moto G-class phone.

## Product Shape

GOFFY has three deployment layers:

1. Android app: installable debug/release app for safe iteration.
2. Default home: user-selectable launcher that replaces the normal home screen.
3. ROM shell: GOFFY preinstalled as a non-privileged system app after ROM gates.

The same UI must work in all three layers. ROM mode may add boot and setup
integration later, but it must not rely on privileged permissions for ordinary
agent actions.

## Interaction Model

The home surface has one primary loop:

```text
observe -> understand -> discover -> plan -> authorize -> execute -> verify -> report
```

The user should always see which part of the loop is active. The system should
never feel like a black box.

Primary inputs:

- Type: always available, deterministic, and fastest for testing.
- Push-to-talk: foreground-only, no background recording.
- Camera: foreground-only, no image persistence unless the user explicitly asks.
- Touch: approval, cancellation, details, retry, memory controls, and app launch.
- Suggestions: contextual, but never automatic execution.

Primary outputs:

- Short answer: concise result at the top of the surface.
- Timeline: exact observable events, tools, progress, verification, and failure.
- Voice: optional readout for safe summaries only.
- Detail sheet: structured result, MCP tools used, audit metadata, and next step.

## Core Screens

### Home Command Surface

Purpose: default always-ready shell.

Required elements:

- GOFFY title and connection state.
- Center orb with visible state.
- Command input anchored near thumb reach.
- Push-to-talk button.
- Camera button.
- Execution target indicator: PHONE, MAC, or CLOUD.
- Mac Hub connection chip.
- Local model status chip.
- Empty-state task timeline.
- Safe action suggestions.

Old-phone constraints:

- No continuous blur.
- No particle systems.
- Static background in GOFFY LITE.
- Orb animation disabled in battery saver and during sustained load.
- Timeline uses bounded items and lazy rendering.

### Task Timeline

Purpose: make every action observable and auditable.

Each task card shows:

- User intent summary.
- Execution target.
- Permission level.
- Current phase.
- Tool name when known.
- Approval status when applicable.
- Verification status.
- Compact result or error.

Expandable details show:

- Observe/plan/authorize/tool/result/verify events.
- MCP or phone tools used.
- Structured result fields.
- Redacted audit record status.
- Retry/cancel availability.

### Approval Sheet

Purpose: make side effects explicit before they occur.

Approval copy must state:

- The exact tool.
- The exact target.
- The exact side effect.
- The arguments that matter.
- Expiry time.
- What GOFFY will not do.

Approval requirements:

- One visible user action.
- Single-use.
- Exact task, tool, and argument binding.
- Expiring.
- No background approval.
- Server-validated approval artifact before any remote CONFIRM Mac execution.

### Device Map

Purpose: show the operating environment as a connected system.

Nodes:

- Phone local engine.
- Mac Hub.
- MCP registry.
- Optional local model.
- Cloud unavailable/available state.

Edges:

- USB loopback.
- LAN only when explicitly configured.
- MCP sessions.
- Active task route.

This map should be read-only at first. Configuration actions require separate
approval and setup flows.

### Lens Surface

Purpose: camera-based understanding without surveillance.

Modes:

- QR pairing.
- QR content read.
- OCR text read.
- Future visual explanation.

Rules:

- Camera opens only from visible user action.
- Camera closes immediately after result, cancellation, or navigation away.
- No background capture.
- No image persistence by default.
- Preview starts in GOFFY LITE with minimal overlays.

### Memory And Audit

Purpose: make learned state inspectable and removable.

Sections:

- Recent terminal task audit.
- Hub operator audit.
- Approved long-term memory.
- Retention and delete controls.

Rules:

- Raw secrets are never stored.
- Memory has provenance and timestamp.
- User can inspect, edit, and delete memory.
- Restored audit is display-only and cannot revive authority.

### Setup And Recovery

Purpose: make the phone recoverable and safe to repurpose.

Flows:

- Pair Mac over USB-loopback QR bundle.
- Rotate paired token.
- Forget this Mac.
- Revoke this phone.
- Export diagnostic bundle with redaction.
- ROM feasibility checklist.
- Stock restore checklist.

ROM-specific flows must stay gated until bootloader unlock, restore archive,
and rollback evidence are present.

## Visual Direction

GOFFY should look like a focused instrument panel, not a generic chat screen.

Base style:

- Deep graphite background.
- Cyan system accent for PHONE.
- Green-blue route accent for MAC.
- Amber caution accent for approvals.
- Red only for blocked/destructive/error states.
- High-contrast text.
- Large touch targets.
- 720p-first spacing.

Signature orb:

- Idle: static or slow breath depending on performance mode.
- Listening: pulse ring.
- Reasoning: subtle ripple.
- PHONE route: inward pulse.
- MAC route: lateral sweep.
- CLOUD route: upward arc only when cloud exists.
- Approval: amber lock ring.
- Verified: short green-blue check sweep.
- Error: still red outline, no frantic animation.

Typography:

- Use the existing Android font stack until a bundled font is justified by APK
  budget and readability testing.
- Prefer weight, spacing, and color hierarchy over decorative type.

Motion:

- 150-250 ms purposeful transitions.
- Reduced motion honors Android setting.
- No animation that blocks command input.

## Performance Modes

GOFFY LITE is the default for the Moto G-class target.

| Mode | Use | Behavior |
| --- | --- | --- |
| GOFFY LITE | Default Moto mode | Static background, static orb or 30 FPS short pulses, no continuous model, aggressive cleanup |
| GOFFY BALANCED | Proven capable phone | Lightweight orb animation, smoother cards, voice and camera modules lazy-loaded |
| GOFFY ULTRA | Future capable hardware | Richer visual effects and optional local models after measured thermal/battery proof |

Mode selection must be explicit or evidence-based. GOFFY must not silently enable
heavier visuals because the UI looks better.

## ROM Home Behavior

The ROM home surface should:

- Boot into GOFFY after Android setup completes.
- Remain user-recoverable.
- Keep Settings reachable.
- Keep emergency calling and lock-screen behavior untouched.
- Avoid privileged permissions unless a separate ROM ADR proves necessity.
- Use the same signed APK artifact path planned by ROM-0.

The ROM must not:

- Disable Android security features.
- Hide system recovery paths.
- Grant GOFFY broad file, mic, camera, or shell authority.
- Ship a large local model by default.
- Replace rollback planning with confidence claims.

## Near-Term UI Build Order

1. Create design tokens for colors, spacing, state, and performance mode.
2. Replace the current orb placeholder with a lightweight stateful orb.
3. Add a real empty/active/verified/failed timeline visual hierarchy.
4. Add the device map as read-only status.
5. Add approval sheet copy templates shared with audit.
6. Add a memory/audit viewer shell.
7. Add reduced-motion and battery-saver behavior.
8. Add screenshot-based UI smoke tests.

## Acceptance Criteria

A design-driven UI increment is done only when:

- GOFFY LITE remains smooth on the Moto G target.
- Command input is never blocked by animation or network work.
- Every visible side-effecting action has an approval surface.
- Every verified task visibly shows where it ran and which tool was used.
- Camera and microphone indicators are visible only during foreground use.
- The UI can be used as Android HOME without privileged permissions.
- Accessibility labels exist for orb state, target, approval, and task phase.
- Screenshots are captured for idle, approval, executing, verified, and failed states.

## Open Decisions

- Whether GOFFY ships a custom bundled font or uses platform fonts.
- Whether the orb should be pure Compose canvas or vector drawable plus Compose
  state effects.
- Whether the device map belongs on the home surface or a diagnostics sheet.
- How much memory/audit history appears before requiring a detail sheet.
- Which launcher affordances are essential: app drawer, favorites, search, or
  only GOFFY command plus Settings.
