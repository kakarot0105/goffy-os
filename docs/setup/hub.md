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
Hub configuration, every WebSocket tool connection is rejected.

Non-local binding requires `GOFFY_HUB_ALLOW_LAN=true` plus existing
`GOFFY_HUB_TLS_CERT_FILE` and `GOFFY_HUB_TLS_KEY_FILE` paths. This is a transport
guard, not a pairing system. Milestone 0 has no token rotation or device
revocation, so localhost remains the recommended mode.

## Tool request shape

Send a `ToolInvocation` envelope whose payload names `mac.system_info` and has an
empty `arguments` object. The Hub emits `ToolProgress`, `ToolResult`, and
`VerificationResult` envelopes with the invocation message ID as correlation ID.

Run `python scripts/demo_hub.py` while the Hub is active to exercise the flow.
