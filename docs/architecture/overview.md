# Architecture Overview

GOFFY OS is now ROM-first: the target deployment is a recoverable GOFFY Android
ROM or GSI-derived system image on the Moto G `kansas` hardware. The current
Android app/default-launcher layer remains the safe bootstrap and fallback while
ROM feasibility is proven. Across both forms, GOFFY separates intent, policy,
transport, and capability execution so no model or UI can directly acquire
ambient authority. The current runtime has five offline PHONE tools, one
authenticated MAC tool, and a redacted Android-local audit trail for terminal
tasks, not a general command channel.

```text
GOFFY ROM or bootstrap Android command surface
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
terminal task reducer -> app-private Android audit SQLite (50 max, terminal-only, redacted)
Hub operator audit -> bounded hash-chained control-plane events (pairing / WebSocket / MCP)
```

All routes emit the same typed preparation, progress, result, error, and
verification states. PHONE tools require no Hub configuration and never open a
network connection. Android opens a fresh WebSocket for each Mac task, requests
only the already-routed tool, validates the returned capability, and then sends
one tool invocation. It succeeds only after a structured result followed by a
separate verification event. Discovery and pre-send disconnects may be retried
up to two times. Once invocation bytes are sent, disconnects fail closed and are
not replayed. A whole attempt is bounded to 35 seconds.

After a task reaches `VERIFIED`, `UNVERIFIED`, `FAILED`, or `CANCELLED`,
Android may persist one redacted audit row and merge it back into the visible
timeline on restart. Restore is display-only: structured result content, pending
approval state, active work, and execution authority are not revived.

## Trust boundaries

1. Phone input is untrusted. Anchored rules reject appended instructions instead of expanding authority.
2. Hub configuration requires an absolute `/ws/v1` endpoint. Release mode expects `wss`; debug cleartext is loopback-only.
3. Every wire message is versioned and strictly validated by both Python and Kotlin models.
4. Authentication is invocation-scoped through the `Authorization` header; the token stays out of URLs and saved state.
5. Explicit paired mode separates loopback bootstrap administration from SAFE
   tool access. Each generated credential ID becomes a distinct WebSocket/MCP
   principal, while client device ID remains descriptive metadata only.
6. Paired bearer digests and bounded metadata use a versioned owner-only SQLite
   store. One-time challenges are memory-only, short-lived, attempt-bounded, and
   discarded on restart.
7. USB-loopback pairing bundles wrap one challenge with an exact `/ws/v1`
   endpoint plus public Hub identity metadata. Android requires that identity
   fingerprint before redemption, requires the redemption response to match it,
   and persists it with the paired credential. These are QR-ready transfer
   payloads, not trusted LAN onboarding.
8. Paired mode creates an owner-only Hub identity file and exposes only its
   stable fingerprint through loopback bootstrap administration. Certificate or
   public-key Hub proof and LAN trust remain future trust-boundary work.
9. Credential revocation persists before indexed live WebSocket and MCP sessions
   are terminated. New requests recheck the digest store.
10. Hub operator audit records only bounded control-plane metadata and is exposed
    through loopback bootstrap administration. Paired mode persists retained
    events in an owner-only SQLite hash chain; non-paired mode stays volatile.
11. GOFFY protocol, MCP metadata, and tool contract versions are checked separately.
12. Remote discovery only confirms or disables a locally known tool. It never adds
   a route, permission, or executable capability.
13. The Hub consumes discovery on one invocation attempt and currently registers
   only SAFE read-only, non-destructive, idempotent, closed-world Mac tools with
   closed object schemas.
14. Fixed gateways allow only the documented typed tool names; no command-string capability exists.
15. The PHONE registry is sorted, immutable, size-bounded, and uses closed MCP-shaped
   schemas. It cannot execute tools or grant approval.
16. The router sources PHONE permission from the registry, and the gateway rechecks
    compiled name, target, permission, typed arguments, and timeout before source access.
17. The battery source is read once, requires no permission, and must return a percentage from 0 through 100.
18. Device info contains display/home-shell status fields and excludes stable device, network, account, and build identifiers.
19. Mutating PHONE tools require an exact-task, exact-tool, exact-arguments,
   expiring, single-use approval.
20. Terminal-task audit rows are written only after `UNVERIFIED`, `VERIFIED`,
    `FAILED`, or `CANCELLED`; process death before then leaves no synthetic
    success row.
21. Audit retention is bounded to the newest 50 rows and stores only closed
    metadata, not raw commands, arguments, results, device info, approval text,
    or free-form summaries.
22. Restored audit entries are result-free, display-only terminal cards. They
    cannot revive pending approval, active execution, or authority.
23. Audit read/write/corrupt-row failure degrades the audit badge without
    rewriting the task verdict and without background retry.
24. Flashlight success requires a matching CameraManager callback and releases the
   callback immediately; it never opens an image stream.
25. A typed result carries data; a separate verification event is the success boundary.
26. Local cancel stops the active coroutine; MAC cancellation does not guarantee Hub-side termination.
27. The Hub rejects duplicate message IDs within a connection and applies the
    configured message-size limit in both transport directions.
28. `/mcp` validates exact Host and Origin allowlists, bearer authentication,
    message bounds, and concurrency before registry execution.
29. The Hub seals registry definitions before serving. Health probes can only
    remove or restore those definitions and cannot mutate their policy metadata.
30. Health never grants authority: clients see only compiled definitions that pass
    their current bounded probe. Admission validates availability and arguments
    before `accepted`; later health changes block new calls, not admitted work.

## Performance posture

The Android shell defaults to GOFFY LITE: static background, static orb, no
camera/microphone capture initialization until visible user action, no polling,
and no local model. Phone state is
read only after a matching user command. Terminal-task audit persistence is
bounded to the newest 50 SQLite rows, read on startup, and written once on the
existing IO dispatcher after terminal state; there is no polling, WorkManager,
or background retry. Hub operations are asynchronous and timeout-bounded.
Hub operator audit appends tiny closed metadata events to a bounded in-memory
deque and, in paired mode, one owner-only SQLite row per event. It performs no
body capture, polling, or background upload.

Hub health checks are Mac-side only: one startup pass, then a 30-second default
sleep between passes, at most four concurrent probes, and a five-second maximum
per probe. The current probe uses local platform APIs and performs no network I/O.
Android re-discovers before every Mac invocation. MCP clients re-run `tools/list`;
the Hub signals changed availability over authenticated MCP GET/SSE without
introducing Android polling.

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
The server advertises `tools.listChanged=true`. Health transitions publish the
standard empty list-change notification through registered SDK sessions. Each
session has a random, bounded in-memory replay store, and reconnecting GET/SSE
streams resume with `Last-Event-ID`; no result payload is retained or shared.
Both transports adapt the same bounded `ToolRegistry`; neither transport defines
or executes tools independently.
