# Protocol Fixtures

Language-neutral JSONL fixtures are validated by both the Python protocol models
and Android's strict Kotlin codec. Keep each line as one complete wire envelope.
The Mac flow includes discovery and invocation IDs with separate correlation chains.

`pairing-bundle-v1.json` is the QR-onboarding payload shape for the current
USB-loopback pairing slice. It is validated against
`protocol/schemas/pairing-bundle.schema.json` and intentionally declares
`trustedLanSupported=false` until certificate or public-key onboarding exists.
