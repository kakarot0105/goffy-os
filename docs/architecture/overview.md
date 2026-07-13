# Architecture Overview

GOFFY OS separates intent, policy, transport, and capability execution so no
model or UI can directly acquire ambient authority.

```text
Android command surface
        |
        | versioned authenticated WebSocket
        v
FastAPI Hub -> protocol validation -> authorization -> fixed tool registry
                                                        |
                                                        v
                                                narrow Mac capability
```

The initial slice supports one read-only MAC tool. MCP-native discovery and
transport adapters arrive in Milestone 3; the Milestone 0 registry already
publishes MCP-shaped input/output schemas and annotations so that migration does
not change the security boundary.

## Trust boundaries

1. Phone input is untrusted, even after pairing.
2. Every wire message is versioned and schema-validated.
3. Authentication establishes device identity, not action authorization.
4. The registry decides whether a named capability exists.
5. Tool metadata identifies target, permission, timeout, and side effects.
6. Tool output is schema-validated before it is reported as successful.
7. Verification is a separate event from execution.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone initialization, no polling, and no local model. Hub operations
are asynchronous and timeout-bounded. Histories and audit retention will be
bounded when persistence is introduced.
