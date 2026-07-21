# Protocol Fixtures

Language-neutral JSONL fixtures are validated by both the Python protocol models
and Android's strict Kotlin codec. Keep each line as one complete wire envelope.
The Mac flow includes discovery and invocation IDs with separate correlation chains.

`pairing-bundle-v3.json` is the QR-onboarding payload shape for the current
USB-loopback pairing slice. It is validated against
`protocol/schemas/pairing-bundle.schema.json` and intentionally declares
`trustedLanSupported=false` plus a `goffy.hub.trust.v1` contract with absent
public-key and certificate pins until trusted onboarding exists.
