# Protocol Events

Wire events use the schemas in `protocol/schemas` and the typed Python models in
`protocol/python/goffy_protocol`.

The current Android-to-Hub slice is captured in
`protocol/fixtures/mac-system-info-flow.jsonl`:

1. `ToolInvocation` for `mac.system_info` with empty `arguments`
2. `ToolProgress` with `stage=accepted` and `sequence=0`
3. `ToolProgress` with `stage=completed` and `sequence=1`
4. `ToolResult`
5. `VerificationResult`

Android's Kotlin codec validates the same envelope shape, correlation ID,
execution target, and event ordering before the UI treats the flow as
successful. `ToolResult` and `VerificationResult` are intentionally separate.
