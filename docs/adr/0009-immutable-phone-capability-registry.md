# ADR 0009: Immutable PHONE capability registry

- Status: Accepted
- Date: 2026-07-13

## Context

PHONE tool metadata was repeated across deterministic routing and gateway
execution. The five implementations had typed runtime checks, but Android lacked
one bounded catalog for schemas, permissions, targets, annotations, and timeouts.
Using discovery or a JSON fixture as authority would let descriptive data expand
local execution and weaken the exact-approval boundary.

## Decision

- Add a sorted, immutable Android registry for the five compiled PHONE tool names.
- Give every descriptor MCP-shaped title, description, closed input/output JSON
  Schemas, safety annotations, semantic tool version, PHONE target, GOFFY
  permission, and bounded timeout.
- Limit the registry to 16 capabilities, 8 KiB per descriptor, 32 KiB aggregate,
  and 30 seconds per tool.
- Keep executable typed-argument matchers private to Android. The registry can
  describe and match a plan but cannot access device sources or execute a tool.
- Source PHONE permissions from the registry in deterministic routing. Re-resolve
  the compiled descriptor in the gateway and require exact target, permission,
  typed arguments, and SAFE or single-use CONFIRM authorization before source access.
- Commit one sorted language-neutral snapshot under `shared/fixtures`. Kotlin
  compares compiled descriptors to it; Python independently validates metadata
  and both JSON Schemas.
- Do not export CONFIRM PHONE tools over MCP until an approval-capable transport
  is designed. Discovery data, annotations, and fixtures never grant authority.

## Consequences

Permission downgrades, schema drift, unknown tools, wrong targets, and malformed
plans now fail before Android state is read or changed. The static registry adds
only a small lazy allocation and no polling, network use, model load, or background
work. Command matching, source bindings, output verification, and approval grants
remain executable local policy, so the shared snapshot cannot become an ambient
capability channel.

Future Phone MCP work can reuse the pure descriptors, but it must add explicit
approval transport and audit semantics before exposing CONFIRM entries. Tool-health
checks, list-change notifications, and physical Moto G performance measurements
remain separate milestones.

## References

- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [MCP schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
