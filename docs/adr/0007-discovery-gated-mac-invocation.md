# ADR 0007: Discovery-gated Mac invocation

- Status: Accepted
- Date: 2026-07-13

## Context

Android currently knows the one allowed Mac tool locally and the Hub has a typed
registry, but the client invokes without first proving that the connected Hub has
a compatible capability. GOFFY needs discovery before execution without allowing
remote metadata to grant new authority or pretending its application protocol is
already an MCP transport.

## Decision

- Introduce GOFFY protocol `0.2.0` with `CapabilityDiscoveryRequest` and
  `CapabilityDiscoveryResponse`. This is a breaking sequencing change from `0.1.0`.
- Keep the GOFFY envelope version separate from the MCP metadata revision
  `2025-11-25` and the `mac.system_info` tool contract version `1.0.0`.
- Request only the routed, locally allowlisted tool on the invocation's existing
  authenticated WebSocket. Do not enumerate the full registry in this slice.
- Return MCP-shaped tool fields and JSON Schema 2020-12 plus namespaced GOFFY
  metadata for permission, execution target, timeout, and tool version.
- Treat MCP annotations as descriptive hints only. Android's local allowlist and
  exact compatibility checks remain authoritative.
- Require one compatible `mac.system_info` descriptor before the Hub accepts its
  invocation. Missing, duplicate, malformed, mismatched, or undiscovered tools
  fail before progress or handler execution.
- Require all four safety annotations and closed object schemas, reject duplicate
  message IDs within a connection, and bound inbound and outbound envelopes.
- Emit Android `Ready` only after discovery succeeds and invocation bytes are
  accepted by the WebSocket send queue.
- Retry only while the invocation has not been sent. Bound a complete attempt to
  35 seconds and cancel the socket on timeout.
- Add no cache, polling, background connection, dynamic list notification, or
  model-driven tool selection.

## Consequences

Every Mac task gains one small local round trip and an observable compatibility
gate. Old `0.1.0` clients and Hubs fail cleanly instead of silently mixing message
sequences. The metadata is aligned with MCP tools but `/ws/v1` remains GOFFY's
strict application protocol; a standards-compliant MCP JSON-RPC transport remains
a separate Milestone 3 deliverable.

## References

- [MCP lifecycle and version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP tool discovery](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [MCP tool schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
