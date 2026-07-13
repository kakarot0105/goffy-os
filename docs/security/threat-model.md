# Initial Threat Model

## Assets

- Mac files, applications, repositories, clipboard, and local services
- Phone sensors, notifications, notes, and user context
- Pairing credentials, tool outputs, audit history, and future model prompts

## Primary threats and current controls

| Threat | Current control | Remaining work |
| --- | --- | --- |
| Unauthenticated tool use | Fail-closed bearer token check | Pairing and rotation |
| Accidental network exposure | Localhost default; LAN requires TLS files | Pairing and network allowlist |
| Command injection | No subprocess API; fixed registry | Review every future tool |
| Protocol confusion | Explicit version and strict models | Compatibility test matrix |
| Oversized messages | Configured receive-size check | Transport-level rate limiting |
| Host information leakage | Status, OS family, and architecture only | User-visible field policy |
| Secret commits | Ignore rules and security scan | Repository secret-scanning service |
| Misleading success | Output validation and verification event | Tool-specific state re-read |

## Non-goals for Milestone 0

The development token is not a pairing system. The WebSocket is not approved for
LAN use. There is no certificate provisioning, secure mobile token storage,
revocation, rate limiting, or persistent audit log yet.
