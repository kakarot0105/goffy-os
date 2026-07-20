# ADR 0027: Verified modelDebug Runtime Setting Control

Status: Accepted

Amended by ADR 0028, which wires `modelDebug` provider execution as a bounded
observe-only unsupported-command timeline task while keeping model output
non-executable.

Date: 2026-07-20

## Context

GOFFY needs a path to enable a small on-phone model for local intent
observations, but normal GOFFY LITE builds must stay responsive on the Moto G and
must not ship the LiteRT-LM runtime or model payloads by default.

The previous slice added a `modelDebug` build type that compiles the real
LiteRT-LM provider while keeping normal `debug` and `release` runtime classpaths
free of LiteRT-LM. The next step is a user-visible runtime setting control for
that developer/runtime-validation variant.

## Decision

Add a foreground local-model runtime setting control that is available only when the
runtime-capable provider is present and developer runtime activation is allowed.

Persist only one non-sensitive boolean: whether the user enabled observe-only
local-model fallback. Store it in app-private Android preferences through
`LocalModelRuntimeSettingsStore`. Apply a requested change only after the write
commits and the stored value is read back with the exact requested value.

Resolve the optional provider through a fixed local class name. Normal GOFFY LITE
builds do not include that class or the LiteRT-LM dependency, so the resolver
returns `null`, runtime controls stay hidden, and status remains fail-closed.
ADR 0028 later wires provider execution only as an observe-only unsupported
command timeline task.

Do not wire model generation into executable routing in this decision.
Deterministic routes and explicit approvals remain authoritative.

## Consequences

- `modelDebug` can now persist a foreground enable/disable setting without
  adding LiteRT-LM to normal builds.
- The settings write is observable in the UI and fails closed if storage cannot
  be verified.
- No new default Android dependency is added for a single boolean, preserving the
  current GOFFY LITE footprint.
- Android Preferences DataStore remains the preferred option if settings become
  multi-field, flow-driven, migrated, or shared across components.
- Executable model routing still requires a future async router handoff,
  idle-unload behavior, and real Moto responsiveness evidence.

## Rejected Alternatives

- Add Preferences DataStore now. Rejected because this slice stores one
  non-sensitive app-private boolean, and adding a new dependency to the default
  app is unnecessary until settings become larger or flow-driven.
- Expose the control in normal `debug` and `release`. Rejected because users
  could enable a runtime that is intentionally absent from GOFFY LITE.
- Let the local model produce executable routes immediately. Rejected because
  model output must remain non-authoritative until latency, unload, quality, and
  safety gates are verified on the Moto G.
