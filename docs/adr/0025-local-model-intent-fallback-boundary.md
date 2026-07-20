# ADR 0025: Local model intent fallback boundary

## Status

Accepted

## Context

GOFFY should eventually feel like a Jarvis-style phone environment, but the Moto
G target has about 4 GB RAM and must stay responsive. A local model can improve
natural-language tolerance, but unrestricted model routing would weaken the
existing permission model and make tool execution harder to verify.

The current Android app already has deterministic, typed routes for supported
PHONE and MAC tools. Unknown commands fail closed with a visible unsupported
state.

## Decision

- Add a local-model intent boundary in Android without adding a runtime
  dependency or shipping a model binary.
- Keep the local model disabled by default.
- Keep deterministic routing authoritative. Supported exact routes must return
  before a local-model fallback is consulted.
- For unsupported commands, allow a future model to return only a bounded
  observation or intent candidate.
- Do not allow local-model output to become a `GoffyExecutionPlan`.
- Enforce the initial prompt and candidate-text bounds now. Treat the 512 MB
  model file budget and bounded idle unload as declared gates that must be wired
  before any runtime dependency or model binary is enabled.
- Reject blank commands before they become model prompts.

## Consequences

The project can now integrate LiteRT-LM or another measured runtime later
without changing the safety contract: the model may help GOFFY understand what
the user might mean, but the deterministic router, tool registry, permissions,
approvals, and verification still decide whether anything can run.

This delays visible model behavior, but prevents a heavy dependency or model
asset from landing before the Moto benchmark proves it fits.

## Rejected alternatives

- Add a model dependency immediately. Rejected because no real Moto benchmark
  has proven startup, memory, battery, or thermal safety.
- Let model output map directly to tool names. Rejected because tool authority
  must come from typed registries, not generated text.
- Use MediaPipe LLM Inference API for first integration. Rejected because Google
  marks that API maintenance-only and recommends LiteRT-LM for Android/Kotlin
  projects.
- Use llama.cpp in the Android app first. Rejected for now because the native
  build and packaging surface is broader than a disabled boundary and LiteRT-LM
  is the preferred Android/Kotlin candidate to benchmark first.
