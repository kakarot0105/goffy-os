# Architecture Overview

GOFFY OS separates intent, policy, transport, and capability execution so no
model or UI can directly acquire ambient authority. The current runtime has one
offline PHONE tool and one authenticated MAC tool, not a general command channel.

```text
Android command surface
        |
        | anchored deterministic route
        v
deterministic router
        +--> PHONE -> fixed local gateway -> BatteryManager
        |                              `-> SAFE phone.battery.status
        |
        `--> MAC -> strict codec -> authenticated per-invocation WebSocket
                                      `-> FastAPI Hub -> SAFE mac.system_info
```

Both routes emit the same typed preparation, progress, result, error, and
verification states. `phone.battery.status` requires no Hub configuration and
never opens a network connection. Android opens a fresh
WebSocket for each invocation, sends one tool request, and succeeds only after
it receives a structured result followed by a separate verification event.
Retries are limited to connection failures before send. Once the invocation
bytes are sent, disconnects fail closed and are not replayed.

## Trust boundaries

1. Phone input is untrusted. Anchored rules reject appended instructions instead of expanding authority.
2. Hub configuration requires an absolute `/ws/v1` endpoint. Release mode expects `wss`; debug cleartext is loopback-only.
3. Every wire message is versioned and strictly validated by both Python and Kotlin models.
4. Authentication is invocation-scoped through the `Authorization` header; the token stays out of URLs and saved state.
5. Fixed gateways allow only `mac.system_info` or `phone.battery.status`; both are SAFE and read-only.
6. The battery source is read once, requires no permission, and must return a percentage from 0 through 100.
7. A typed result carries data; a separate verification event is the success boundary.
8. Local cancel stops the active coroutine; MAC cancellation does not guarantee Hub-side termination.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone initialization, no polling, and no local model. Battery status
is read only after a user command. Hub operations
are asynchronous and timeout-bounded. Histories and audit retention will be
bounded when persistence is introduced.

The five-envelope fixture for this slice lives at
`protocol/fixtures/mac-system-info-flow.jsonl` and is validated by both Android
and Python tests.
