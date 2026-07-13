# ADR 0001: Foundation boundaries

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY OS needs a useful first path from an Android command surface to a Mac
capability without granting arbitrary host access or committing to a large local
model.

## Decision

- Use Kotlin and Jetpack Compose for the Android surface with min SDK 26.
- Use Python 3.12+, FastAPI, Pydantic, and WebSockets for the first Hub.
- Bind the Hub to localhost unless LAN mode is explicitly enabled.
- Use a fixed typed registry rather than a shell/command endpoint.
- Model tool schemas and annotations after MCP, while deferring a real MCP
  server transport to Milestone 3.
- Default the phone UI to GOFFY LITE and defer active animations.

## Consequences

The first slice is testable and narrow, but it is not yet usable from a physical
phone across the network. Pairing, TLS, audit persistence, and Android transport
must be completed before LAN use.
