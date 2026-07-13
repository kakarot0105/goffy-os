# Shared

Reserved for language-neutral fixtures and constants that do not belong to the
versioned wire protocol.

`fixtures/phone-tool-capabilities.json` is the canonical sorted PHONE capability
snapshot. Kotlin compares every compiled descriptor to it, while Python validates
the same MCP-shaped metadata and JSON Schemas independently.
