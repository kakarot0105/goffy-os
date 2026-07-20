# ADR 0028: Observe-Only Local Model Execution

## Status

Accepted

## Context

GOFFY OS is targeting old Android hardware, so any on-phone model work must be
bounded, foreground-visible, and secondary to deterministic routing. Earlier
slices added a disabled-by-default local-model quality gate, the optional
`modelDebug` LiteRT-LM provider compile path, and verified foreground runtime
setting control. The remaining gap was that an enabled provider could report
`READY`, but unsupported commands still could not exercise it from the app
timeline.

The security constraint is unchanged: model output cannot create an executable
route, choose a permission level, or approve a tool invocation.

## Decision

Wire `modelDebug` provider execution only as an observe-only fallback for
unsupported commands:

- Deterministic routes run first and bypass the local model entirely.
- Unsafe unsupported commands rejected by the prompt boundary do not call the
  provider.
- The provider runs only when foreground status is `READY` and observation
  execution is explicitly available in the build.
- The ViewModel records a PHONE timeline task with no tool name, no permission,
  no result payload, and a terminal failed or cancelled phase.
- Passing model output records a non-executable hint such as a suggested target
  plus confidence.
- Runtime failures and timeout failures become rejected observations.
- Cancellation propagates through the active task job.

## Consequences

`modelDebug` can now validate real on-phone LiteRT-LM behavior from the app UI
without weakening the permission model. The default `debug` and `release` GOFFY
LITE builds still do not include or load LiteRT-LM. A model hint can improve
future router development, but it does not cause any phone, Mac, or cloud tool
to run.

Production activation still needs Moto responsiveness evidence, idle-unload
evidence, label-quality evidence with the selected model, and a user-facing
acceptance gate.

## Rejected Alternatives

- Let the model create executable routes immediately. Rejected because it would
  bypass deterministic tool schemas and approval classification.
- Block `submitCommand` synchronously while generation runs. Rejected because it
  risks visible UI stalls on the Moto target.
- Add a separate generic model-command tool. Rejected because that would look
  like an execution capability while the output is only advisory.
