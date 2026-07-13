# GOFFY OS Agent Instructions

## Mission

Build a local-first, phone-first, MCP-native agentic operating environment in
small, verified increments. The observe-plan-act-verify-learn loop must remain
visible to the user.

## Required engineering loop

1. Inspect `README.md`, `ROADMAP.md`, relevant ADRs, tests, and current changes.
2. Select one narrow end-to-end task and state its acceptance criteria.
3. Implement the smallest complete change using typed boundaries.
4. Run formatting, linting, type checks, tests, and the security scan.
5. Review implementation and security in a separate pass.
6. Fix high- and medium-severity findings before claiming completion.
7. Update docs and roadmap status when behavior or setup changes.

## Safety invariants

- Never add an arbitrary shell or command-string execution tool.
- Tools must be allowlisted, schema-validated, timeout-bounded, permission
  labeled, and return structured output.
- The Hub binds to localhost unless LAN mode is explicitly configured.
- Authentication fails closed. Do not weaken it to simplify development.
- Do not commit credentials, tokens, private keys, personal data, or `.env`.
- Destructive actions are blocked by default.
- Camera and microphone access must be foreground-only and user-visible.
- Never report success without checking the expected final state.
- Keep phone work bounded for 4 GB RAM hardware; GOFFY LITE is the default.

## Project conventions

- Python: 3.12+, full type annotations, Pydantic at trust boundaries, Ruff, MyPy.
- Android: Kotlin, Compose, min SDK 26, coroutines for asynchronous work.
- Protocol fields use lower camel case on the wire and explicit versioning.
- New major design decisions require an ADR in `docs/adr/`.
- Tests must cover rejection and failure paths, not only happy paths.

<!-- OMC:START -->
<!-- OMC:VERSION:4.9.3 -->
Use oh-my-Codex agents for multi-file implementation and separate verification.
Route implementation to `executor`; route final review to `code-reviewer`,
`security-reviewer`, or `verifier` as appropriate. Prefer evidence over
assumptions and consult official framework documentation before SDK changes.
<!-- OMC:END -->
