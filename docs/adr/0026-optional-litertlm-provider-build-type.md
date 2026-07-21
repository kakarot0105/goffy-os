# ADR 0026: Optional LiteRT-LM Provider Build Type

## Status

Accepted

## Context

GOFFY needs a small on-phone model path for Jarvis-like intent understanding, but
the Moto G target must remain responsive and the default GOFFY LITE APK must not
silently gain a large runtime or model payload. The existing local-model boundary
already keeps generated text non-authoritative and fail-closed, but there was no
production-code compile path for the real LiteRT-LM Android SDK outside
instrumentation tests.

Google's LiteRT-LM Kotlin API is the preferred reuse target because it is the
maintained Google AI Edge Android path, is Apache-2.0, provides a Gradle Android
artifact, and exposes an `Engine` API that can be initialized off the UI thread
and explicitly closed.

## Decision

Add a dedicated Android `modelDebug` build type for provider validation:

- Normal `debug` and `release` builds remain GOFFY LITE and do not depend on
  LiteRT-LM.
- `modelDebugImplementation` depends on
  `com.google.ai.edge.litertlm:litertlm-android`.
- `android/app/src/modelDebug` contains the real LiteRT-LM provider source.
- The provider uses CPU backend, `Dispatchers.Default`, app cache directory,
  bounded output collection, and explicit `use`/close blocks.
- The provider is wired only to the suspend observe-only local-model provider
  boundary, not the synchronous deterministic router.
- User activation still defaults to disabled until a visible, tested enablement
  and unload lifecycle exists.
- CI and `verify_all.py` run `:app:processModelDebugManifest` and compile
  `:app:compileModelDebugKotlin` while the APK budget guard verifies the normal
  release APK remains runtime-free.

## Consequences

The real LiteRT-LM Android API can now compile against GOFFY's production source
boundaries without inflating default GOFFY LITE builds. This keeps provider code
from rotting while preserving the safety invariant that deterministic routes are
the only executable routes.

The tradeoff is that `modelDebug` is not a user-facing production activation
path. A later slice still needs visible user enablement, app-private model
installation/selection, idle unload behavior, UI responsiveness measurements,
and physical Moto verification before the model can be enabled.

## Alternatives Considered

- Add LiteRT-LM to normal `implementation`. Rejected because it would regress the
  default release runtime and violate the GOFFY LITE budget.
- Keep LiteRT-LM only in `androidTestImplementation`. Rejected because it does
  not prove production source can compile against the provider boundary.
- Create a separate Android library module. Deferred because a build type gives
  enough isolation with less project structure churn for this stage.
