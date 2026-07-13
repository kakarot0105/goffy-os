# ADR 0008: Official MCP Streamable HTTP boundary

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY's `/ws/v1` application protocol already discovers and invokes the Hub's
typed registry, but generic MCP clients cannot use that envelope. Reimplementing
MCP JSON-RPC inside `/ws/v1` would mix incompatible lifecycle, correlation, and
security semantics. Defining tools a second time through framework decorators
would also create two policy authorities.

## Decision

- Add the official Python MCP SDK v1 as a bounded dependency and expose exact
  `/mcp` Streamable HTTP separately from `/ws/v1`.
- Pin SDK `1.28.1` because GOFFY removes terminated transports from the manager's
  retained session maps to preserve the hard cap. Re-review this workaround before
  every SDK upgrade and remove it when an upstream public cleanup path is available.
- Use the low-level MCP `Server` over the existing `ToolRegistry`. The registry
  remains authoritative for names, schemas, permission metadata, timeouts,
  argument validation, output validation, and execution.
- Support MCP `initialize`, `notifications/initialized`, `tools/list`, and
  `tools/call` with protocol revision `2025-11-25`.
- Run the transport with stateful JSON responses so the SDK enforces initialization
  before operations. Reject `GET` because this slice has no server-initiated events
  or resumability; support authenticated `DELETE` for explicit session cleanup.
- Bind each session to its creating credential through the SDK and reap it after
  60 seconds without an HTTP request. Limit active sessions to eight by default
  and reject malformed or non-initialization requests before session allocation.
- Require the same fail-closed development bearer token used by the Hub. Validate
  exact Host and Origin values before authentication or JSON-RPC parsing.
- Bind request and response bodies to the Hub message limit. Cap the registry at
  32 tools, 24 KiB aggregate metadata, 8 KiB per capability, and 8 KiB per output.
- Allow two concurrent MCP calls by default with a one-second bounded queue wait.
- Return generic, non-secret tool errors. Do not expose registry exception text.
- Keep CONFIRM and SENSITIVE tools unavailable. This transport currently exposes
  only registry-approved SAFE, read-only tools.

## Consequences

Official MCP clients can now discover and call `mac.system_info` without changing
the Android flow or duplicating tool contracts. Stateful JSON enforces lifecycle
ordering without a persistent SSE connection; explicit termination and short idle
reaping bound normal session lifetime. Server push, list-change notifications,
resumption, pairing, token rotation, revocation, per-device rate limits, and the
MCP authorization profile remain future work. The fixed development bearer token
is an authentication placeholder, not a production OAuth deployment.

## References

- [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
