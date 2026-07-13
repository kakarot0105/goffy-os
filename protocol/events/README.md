# Protocol Events

Wire events use the schemas in `protocol/schemas` and the typed Python models in
`protocol/python/goffy_protocol`.

The current discovery-first Android-to-Hub slice is captured in
`protocol/fixtures/mac-system-info-flow.jsonl`:

1. `CapabilityDiscoveryRequest` for the locally routed `mac.system_info`
2. `CapabilityDiscoveryResponse` with one compatible tool record
3. `ToolInvocation` with empty `arguments`
4. `ToolProgress` with `stage=accepted` and `sequence=0`
5. `ToolProgress` with `stage=completed` and `sequence=1`
6. `ToolResult`
7. `VerificationResult`

Android's Kotlin codec validates the same envelope shape, correlation ID,
execution target, and event ordering before the UI treats the flow as
successful. `ToolResult` and `VerificationResult` are intentionally separate.
Discovery metadata confirms local policy; it never creates a new route.
