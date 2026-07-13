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
| Invalid local tool output | Battery percentage is range-checked before result and verification events | Tool-specific state re-read where meaningful |
| Misleading success | Output validation plus separate `VerificationResult` event | Tool-specific state re-read |
| False cancel expectations | UI states that cancel is local-only and Hub completion is not guaranteed | End-to-end cancellation protocol |

## Current non-goals

The development token is not a pairing system. The WebSocket is not approved for
LAN use. There is no trusted certificate provisioning, secure mobile token
storage, token revocation, transport rate limiting, server-side cancellation, or
persistent audit log yet.
