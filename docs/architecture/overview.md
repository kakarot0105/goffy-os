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
        +--> PHONE -> immutable capability registry -> fixed local gateway
        |                                          -> Android typed capabilities
        |                              |-> SAFE battery / device info
        |                              |-> CONFIRM private note / system timer
        |                              `-> CONFIRM callback-verified flashlight
        |
        `--> MAC -> strict codec -> authenticated per-invocation WebSocket
                         |            |-> discover locally allowlisted tool
                         |            `-> invoke only after compatibility gate
                         `--------------> FastAPI Hub -> SAFE mac.system_info

Official MCP client -> authenticated POST /mcp -> MCP SDK -> same ToolRegistry
                                                        ^
bounded health monitor -> sealed registry availability -'
```

All routes emit the same typed preparation, progress, result, error, and
verification states. PHONE tools require no Hub configuration and never open a
network connection. Android opens a fresh WebSocket for each Mac task, requests
only the already-routed tool, validates the returned capability, and then sends
one tool invocation. It succeeds only after a structured result followed by a
separate verification event. Discovery and pre-send disconnects may be retried
up to two times. Once invocation bytes are sent, disconnects fail closed and are
not replayed. A whole attempt is bounded to 35 seconds.

## Trust boundaries

1. Phone input is untrusted. Anchored rules reject appended instructions instead of expanding authority.
2. Hub configuration requires an absolute `/ws/v1` endpoint. Release mode expects `wss`; debug cleartext is loopback-only.
3. Every wire message is versioned and strictly validated by both Python and Kotlin models.
4. Authentication is invocation-scoped through the `Authorization` header; the token stays out of URLs and saved state.
5. GOFFY protocol, MCP metadata, and tool contract versions are checked separately.
6. Remote discovery only confirms or disables a locally known tool. It never adds
   a route, permission, or executable capability.
7. The Hub consumes discovery on one invocation attempt and currently registers
   only SAFE read-only, non-destructive, idempotent, closed-world Mac tools with
   closed object schemas.
8. Fixed gateways allow only the documented typed tool names; no command-string capability exists.
9. The PHONE registry is sorted, immutable, size-bounded, and uses closed MCP-shaped
   schemas. It cannot execute tools or grant approval.
10. The router sources PHONE permission from the registry, and the gateway rechecks
    compiled name, target, permission, typed arguments, and timeout before source access.
11. The battery source is read once, requires no permission, and must return a percentage from 0 through 100.
12. Device info contains four display fields and excludes stable device, network, account, and build identifiers.
13. Mutating PHONE tools require an exact-task, exact-tool, exact-arguments,
   expiring, single-use approval.
14. Flashlight success requires a matching CameraManager callback and releases the
   callback immediately; it never opens an image stream.
15. A typed result carries data; a separate verification event is the success boundary.
16. Local cancel stops the active coroutine; MAC cancellation does not guarantee Hub-side termination.
17. The Hub rejects duplicate message IDs within a connection and applies the
    configured message-size limit in both transport directions.
18. `/mcp` validates exact Host and Origin allowlists, bearer authentication,
    message bounds, and concurrency before registry execution.
19. The Hub seals registry definitions before serving. Health probes can only
    remove or restore those definitions and cannot mutate their policy metadata.
20. Health never grants authority: clients see only compiled definitions that pass
    their current bounded probe. Admission validates availability and arguments
    before `accepted`; later health changes block new calls, not admitted work.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone capture initialization, no polling, and no local model. Phone state is
read only after a matching user command. Hub operations
are asynchronous and timeout-bounded. Histories and audit retention will be
bounded when persistence is introduced.

Hub health checks are Mac-side only: one startup pass, then a 30-second default
sleep between passes, at most four concurrent probes, and a five-second maximum
per probe. The current probe uses local platform APIs and performs no network I/O.
Android re-discovers before every Mac invocation. MCP clients re-run `tools/list`;
server push remains disabled until reconnect-safe delivery is designed.

The seven-envelope discovery-first MAC fixture lives at
`protocol/fixtures/mac-system-info-flow.jsonl` and is validated by both Android
and Python tests.

The canonical sorted PHONE capability snapshot lives at
`shared/fixtures/phone-tool-capabilities.json`. Kotlin compares the compiled
registry to it, and Python independently validates its MCP-shaped metadata and
JSON Schemas. It is a compatibility artifact, not an execution allowlist.

`/ws/v1` remains GOFFY's Android application protocol. Exact `/mcp` is a separate,
session-aware MCP `2025-11-25` Streamable HTTP endpoint implemented by the official
Python SDK. Sessions are credential-bound, explicitly terminable, and idle-reaped.
The server advertises `tools.listChanged=false`; `GET` server push, event replay,
and resumption remain disabled.
Both transports adapt the same bounded `ToolRegistry`; neither transport defines
or executes tools independently.
