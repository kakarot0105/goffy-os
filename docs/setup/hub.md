# Hub Setup

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token'
.venv/bin/goffy-hub
```

`GET /health` is intentionally unauthenticated and returns no private host data.
It reports `degraded` when any registered tool is unavailable and includes
healthy/unavailable counts plus a registry revision, but no names or probe details.
`/ws/v1` requires `Authorization: Bearer <token>`. If the token is absent from
Hub configuration, every WebSocket and MCP tool request is rejected. Each Android
Mac task opens its own authenticated WebSocket, sends a
`CapabilityDiscoveryRequest` for the locally routed tool, validates the response,
then sends one `ToolInvocation`. The Hub consumes that discovery on the invocation
attempt and emits `ToolProgress`, `ToolResult`, and `VerificationResult` or a
terminal `ToolError`.

GOFFY protocol `0.2.0` is required on both sides. Discovery records use MCP
`2025-11-25` tool fields and JSON Schema 2020-12, but `/ws/v1` is not an MCP
JSON-RPC endpoint. Do not connect a generic MCP client to this path.

## MCP client

Exact `/mcp` supports MCP `2025-11-25` initialization, `tools/list`, and
`tools/call` through the official Python SDK. It returns JSON and requires the
session ID issued during initialization for subsequent operations. Authenticated
`GET` opens the session's MCP event stream, and `DELETE` terminates the session.
Disconnected event streams resume with `Last-Event-ID`; an active stream pauses
the 60-second idle timer while remaining inside the active-session cap. The Hub
rotates each stream after 45 seconds so clients reconnect through the bounded
replay path. Run the Hub, then use the repository's official-client demo:

```bash
GOFFY_HUB_TOKEN='replace-with-the-same-development-token' \
  .venv/bin/python scripts/demo_mcp.py
```

The demo succeeds only after negotiating the expected protocol, discovering
exactly `mac.system_info`, calling it with no arguments, and validating the typed
structured output. It never prints the token.

The local MCP Host and Origin allowlists are derived from port `8787`. Override
them only with exact comma-separated values:

```bash
export GOFFY_MCP_ALLOWED_HOSTS='127.0.0.1:8787,localhost:8787'
export GOFFY_MCP_ALLOWED_ORIGINS='http://127.0.0.1:8787,http://localhost:8787'
export GOFFY_MCP_MAX_CONCURRENT_CALLS='2'
export GOFFY_MCP_MAX_ACTIVE_SESSIONS='8'
export GOFFY_TOOL_HEALTH_TIMEOUT_SECONDS='1'
export GOFFY_TOOL_HEALTH_INTERVAL_SECONDS='30'
```

Wildcards are rejected. A native MCP client usually sends no `Origin`; if it does,
the value must match exactly. Non-local binding additionally requires explicit
LAN mode, TLS files, and `GOFFY_MCP_ALLOWED_HOSTS`. These checks do not make LAN
operation production-ready: pairing, revocation, trusted certificate provisioning,
and the MCP authorization profile are still absent.

The Hub seals the registry and completes one health pass before accepting traffic.
It then checks only compiled local probes at the configured interval, with a
five-second hard configuration maximum and four-probe concurrency cap. Unhealthy
tools disappear from `/ws/v1` discovery and MCP `tools/list`; calls fail with the
same generic unknown-or-unauthorized error. Recovery restores the original typed
definition. Android discovers before every Mac invocation, while MCP clients must
explicitly re-run `tools/list` after `notifications/tools/list_changed`. The Hub
keeps only those empty notifications in a random, per-session in-memory replay
store capped at 64 events and 16 KiB. It does not retain tool results, share
cursors between sessions, or replay across termination, idle expiry, or Hub
restart. Unknown, foreign, and evicted cursors replay no retained history; they
receive a fresh re-list signal and attach to the current session's live tail. No
network health probe or busy polling is used by the current `mac.system_info` tool.

Non-local binding requires `GOFFY_HUB_ALLOW_LAN=true` plus existing
`GOFFY_HUB_TLS_CERT_FILE` and `GOFFY_HUB_TLS_KEY_FILE` paths. This is a transport
guard, not a pairing system. Trusted LAN use is still unsupported until pairing,
revocation, and a trusted TLS story exist, so localhost remains the recommended
mode.

## Android debug over USB

1. Start the Hub with `GOFFY_HUB_TOKEN` set.
2. Attach the Android phone by USB.
3. Reverse the Hub port:

   ```bash
   adb reverse tcp:8787 tcp:8787
   ```

4. In the debug app, configure `ws://127.0.0.1:8787/ws/v1`.
5. Run `Show my Mac status` or `Check my Mac status`.

The debug flow uses loopback cleartext only. Release builds should use
`wss://.../ws/v1`.

## Discovery and request shape

First send a `CapabilityDiscoveryRequest` envelope with
`{"toolName":"mac.system_info"}`. A compatible Hub returns one MCP-shaped tool
record correlated to the discovery message ID. Then send a `ToolInvocation`
envelope with the same tool name and an empty `arguments` object. The Hub emits
accepted progress, completed progress, `ToolResult`, and `VerificationResult`
with the invocation message ID as correlation ID.

Invocation before discovery, a second invocation without fresh discovery, or a
different tool name fails with `capability_discovery_required`. The shared
seven-envelope sequence is `protocol/fixtures/mac-system-info-flow.jsonl`.
