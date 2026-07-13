# Protocol Compatibility

The current runtime supports exactly GOFFY protocol `0.2.0`. It introduces a
mandatory discovery-before-invocation sequence, so `0.1.0` clients and Hubs are
intentionally incompatible and fail before payload execution.

Three versions have distinct meanings:

- `protocolVersion=0.2.0` controls GOFFY envelope types, sequencing, and correlation.
- `mcpProtocolVersion=2025-11-25` identifies the metadata shape carried inside
  `/ws/v1`; it is not GOFFY envelope negotiation.
- `_meta.dev.goffy/toolVersion=1.0.0` identifies the `mac.system_info` contract.

Exact `/mcp` independently negotiates MCP protocol `2025-11-25` through the MCP
`initialize` lifecycle. It does not accept GOFFY envelopes. Exact `/ws/v1` accepts
GOFFY protocol `0.2.0` envelopes and does not accept MCP JSON-RPC. Both transports
adapt the same tool contract and registry, so schema or tool-version changes must
remain compatible in both test suites.

Unsupported values are rejected before invocation. Future protocol revisions must
add fixtures for every supported pair; no implicit downgrade is allowed.
