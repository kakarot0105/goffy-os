# Architecture Overview

GOFFY OS separates intent, policy, transport, and capability execution so no
model or UI can directly acquire ambient authority. The current slice is one
deterministic Android-to-Hub action, not a general command channel.

```text
Android command surface
        |
        | exact route: Show/Check [me] my Mac status
        v
deterministic router
        |
        | strict typed codec + authenticated per-invocation WebSocket
        v
FastAPI Hub -> protocol validation -> authorization -> fixed tool registry
                                                        |
                                                        v
                                                SAFE mac.system_info
```

The initial slice supports one read-only MAC tool. Android opens a fresh
WebSocket for each invocation, sends one tool request, and succeeds only after
it receives a structured result followed by a separate verification event.
Retries are limited to connection failures before send. Once the invocation
bytes are sent, disconnects fail closed and are not replayed.

## Trust boundaries

1. Phone input is untrusted. The router accepts only the exact `Show/Check [me] my Mac status` family.
2. Hub configuration requires an absolute `/ws/v1` endpoint. Release mode expects `wss`; debug cleartext is loopback-only.
3. Every wire message is versioned and strictly validated by both Python and Kotlin models.
4. Authentication is invocation-scoped through the `Authorization` header; the token stays out of URLs and saved state.
5. The registry decides whether `mac.system_info` exists and remains SAFE and read-only.
6. `ToolResult` carries data. `VerificationResult` is the success boundary.
7. Local cancel closes Android transport state only and does not guarantee Hub-side termination.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone initialization, no polling, and no local model. Hub operations
are asynchronous and timeout-bounded. Histories and audit retention will be
bounded when persistence is introduced.

The five-envelope fixture for this slice lives at
`protocol/fixtures/mac-system-info-flow.jsonl` and is validated by both Android
and Python tests.
