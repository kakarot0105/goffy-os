# Initial Threat Model

## Assets

- Mac files, applications, repositories, clipboard, and local services
- Phone sensors, notifications, notes, and user context
- Pairing credentials, tool outputs, audit history, and future model prompts

## Primary threats and current controls

| Threat | Current control | Remaining work |
| --- | --- | --- |
| Unauthenticated tool use | Fail-closed bearer token check on every `/ws/v1` invocation | Pairing, rotation, and revocation |
| Token leakage | Bearer token in header only; not in URL, saved state, or stringified config output | Secure mobile storage for future non-debug flows |
| Accidental cleartext exposure | Release endpoint validation requires `wss`; debug cleartext is limited to `localhost` and `127.0.0.1` | Trusted TLS provisioning and pairing |
| Command injection or authority expansion | Anchored routes plus fixed SAFE MAC and PHONE gateways reject appended instructions | Review every future route and tool |
| Replay after partial delivery | Retries are limited to failures before send; sent invocations are not replayed automatically | Idempotency strategy for future mutating tools |
| Protocol confusion | Explicit version plus strict Python and Kotlin codecs | Compatibility test matrix as message types expand |
| Host information leakage | `mac.system_info` returns status, OS family, and architecture only | User-visible field policy for future tools |
| Unnecessary phone-state collection | Battery state is read once only after an explicit command; no receiver, polling, or permission | Field policy for future phone tools |
| Device fingerprinting | Device info is local-only and limited to manufacturer, model, Android release, and SDK; stable identifiers and build fingerprint are excluded | Reassess before persistence or remote transmission |
| Invalid local tool output | Tool-specific type, range, field-length, and control-character checks run before result and verification events | Tool-specific state re-read where meaningful |
| Note approval replay or substitution | Gateway binds a one-time grant to task, tool, exact arguments, and expiry; consumed task IDs cannot be approved twice in one process | Persisted approval audit and process-death recovery policy |
| Note SQL injection or cross-app disclosure | `ContentValues` and selection arguments bind note data; SQLite is app-private and backup is disabled | User-facing note viewer, deletion, and retention controls |
| False note success | Insert and exact row re-read occur in one transaction before a verification event | Physical-device failure-matrix testing |
| Timer intent interception | Resolve only enabled exported allowlisted system handlers, reject the chooser and third-party apps, and pin an explicit component after approval | Moto Clock compatibility matrix |
| Misleading timer verification | Report only a typed dispatch receipt and finish `UNVERIFIED`, never infer unreadable Clock-internal state or UI behavior | Future Clock/MCP integration where state APIs exist |
| Flashlight approval replay or substitution | Bind one-time approval to task, tool, exact Boolean state, and expiry | Persisted approval audit |
| Background camera access through flashlight | Use `setTorchMode` without opening a camera; request no `CAMERA` permission; unregister callback on every exit | Physical OEM validation |
| Misleading flashlight persistence | Mark success only after matching `TorchCallback` and describe verification as point-in-time and nonexclusive | Observe later revocation only if a future user-visible foreground session requires it |
| Multi-camera ambiguity | Prefer logical back-facing flash cameras, then stable camera-ID order; expose no camera identifier | Moto and multi-camera compatibility matrix |
| Android capability creep | Security scan rejects unexpected source-manifest structure and checks exact permissions and queries in freshly merged debug and release manifests | Review allowlist changes as security decisions |
| Misleading success | Output validation plus separate `VerificationResult` event | Tool-specific state re-read |
| False cancel expectations | UI states that cancel is local-only and Hub completion is not guaranteed | End-to-end cancellation protocol |

## Current non-goals

The development token is not a pairing system. The WebSocket is not approved for
LAN use. There is no trusted certificate provisioning, secure mobile token
storage, token revocation, transport rate limiting, server-side cancellation, or
persistent audit log yet.
