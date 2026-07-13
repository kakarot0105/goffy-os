# Hub Setup

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token'
.venv/bin/goffy-hub
```

`GET /health` is intentionally unauthenticated and returns no private host data.
`/ws/v1` requires `Authorization: Bearer <token>`. If the token is absent from
Hub configuration, every WebSocket tool connection is rejected. Each Android
invocation opens its own authenticated WebSocket, sends one `ToolInvocation`,
and waits for `ToolProgress`, `ToolResult`, and `VerificationResult` or a
terminal `ToolError`.

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

## Tool request shape

Send a `ToolInvocation` envelope whose payload names `mac.system_info` and has
an empty `arguments` object. The Hub emits accepted progress, completed
progress, `ToolResult`, and `VerificationResult` envelopes with the invocation
message ID as correlation ID. The shared fixture for this sequence is
`protocol/fixtures/mac-system-info-flow.jsonl`.
