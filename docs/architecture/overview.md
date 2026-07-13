# Architecture Overview

GOFFY OS separates intent, policy, transport, and capability execution so no
model or UI can directly acquire ambient authority. The current runtime has five
offline PHONE tools and one authenticated MAC tool, not a general command channel.

```text
Android command surface
        |
        | anchored deterministic route
        v
deterministic router
        +--> PHONE -> fixed local gateway -> Android typed capabilities
        |                              |-> SAFE battery / device info
        |                              |-> CONFIRM private note / system timer
        |                              `-> CONFIRM callback-verified flashlight
        |
        `--> MAC -> strict codec -> authenticated per-invocation WebSocket
                                      `-> FastAPI Hub -> SAFE mac.system_info
```

All routes emit the same typed preparation, progress, result, error, and
verification states. PHONE tools require no Hub configuration and never open a
network connection. Android opens a fresh
WebSocket for each invocation, sends one tool request, and succeeds only after
it receives a structured result followed by a separate verification event.
Retries are limited to connection failures before send. Once the invocation
bytes are sent, disconnects fail closed and are not replayed.

## Trust boundaries

1. Phone input is untrusted. Anchored rules reject appended instructions instead of expanding authority.
2. Hub configuration requires an absolute `/ws/v1` endpoint. Release mode expects `wss`; debug cleartext is loopback-only.
3. Every wire message is versioned and strictly validated by both Python and Kotlin models.
4. Authentication is invocation-scoped through the `Authorization` header; the token stays out of URLs and saved state.
5. Fixed gateways allow only the documented typed tool names; no command-string capability exists.
6. The battery source is read once, requires no permission, and must return a percentage from 0 through 100.
7. Device info contains four display fields and excludes stable device, network, account, and build identifiers.
8. Mutating PHONE tools require an exact-task, exact-tool, exact-arguments,
   expiring, single-use approval.
9. Flashlight success requires a matching CameraManager callback and releases the
   callback immediately; it never opens an image stream.
10. A typed result carries data; a separate verification event is the success boundary.
11. Local cancel stops the active coroutine; MAC cancellation does not guarantee Hub-side termination.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone capture initialization, no polling, and no local model. Phone state is
read only after a matching user command. Hub operations
are asynchronous and timeout-bounded. Histories and audit retention will be
bounded when persistence is introduced.

The five-envelope MAC fixture for this slice lives at
`protocol/fixtures/mac-system-info-flow.jsonl` and is validated by both Android
and Python tests.
