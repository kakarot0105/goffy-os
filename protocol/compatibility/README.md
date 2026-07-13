# Protocol Compatibility

The current runtime supports exactly GOFFY protocol `0.2.0`. It introduces a
mandatory discovery-before-invocation sequence, so `0.1.0` clients and Hubs are
intentionally incompatible and fail before payload execution.

Three versions have distinct meanings:

- `protocolVersion=0.2.0` controls GOFFY envelope types, sequencing, and correlation.
- `mcpProtocolVersion=2025-11-25` identifies the MCP tool metadata shape only.
- `_meta.dev.goffy/toolVersion=1.0.0` identifies the `mac.system_info` contract.

Unsupported values are rejected before invocation. Future protocol revisions must
add fixtures for every supported pair; no implicit downgrade is allowed.
