# ADR 0010: Bounded tool-health checks

- Status: Accepted
- Date: 2026-07-13

## Context

The Hub previously advertised a static tool list and `listChanged=false`. A tool
could remain discoverable after its narrow implementation became unavailable.
Adding push notifications at the same time would require a durable session and
delivery design that this bounded Streamable HTTP slice does not yet provide.

## Decision

- Require every Hub `ToolDefinition` to provide a narrow asynchronous health probe
  with a timeout of at most five seconds.
- Seal the registry before serving. Health may only remove or restore an existing
  definition; it cannot register a tool or change schemas, permission, target,
  timeout, annotations, handlers, or validation.
- Complete one probe pass before startup, then run a lifecycle-owned monitor with
  a 30-second default interval and at most four concurrent probes. Timeout,
  exception, false, and non-Boolean results all fail closed as unavailable.
- Exclude unavailable tools from GOFFY discovery, MCP `tools/list`, and invocation.
  Return existing generic errors rather than probe details.
- Validate availability and arguments before emitting Android `accepted` progress.
  Execute that exact admitted state; later health changes block new admissions but
  do not retroactively revoke an already accepted call.
- Keep MCP `tools.listChanged=false` and reject Streamable HTTP `GET`. Standard MCP
  clients receive current availability when they explicitly call `tools/list`.
- Keep Android discovery per invocation, so no phone-side polling is introduced.
- Do not add event replay, resumption, MCP client requests, dynamic registration,
  network probes, or server-push delivery in this increment.

## Consequences

Android discovery cannot authorize a tool that the Hub currently considers
unavailable, and MCP list/call requests use the same current state. The health
endpoint exposes aggregate readiness, counts, and a monotonic in-process revision
without revealing tool names or failure details. The monitor adds bounded,
low-frequency Mac work only and is cancelled with application lifespan.

Server push was rejected for now because a bare live SSE stream can miss changes
during disconnect or idle expiry, while the current Hub has no event store or
resumption policy. Persistent health history, operator-visible diagnostics,
pairing identity, and reconnect-safe list-change delivery remain future work.

## References

- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
