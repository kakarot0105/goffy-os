# Contributing to GOFFY OS

GOFFY OS is pre-alpha. Keep changes narrow, testable, and easy to review.

1. Read `AGENTS.md`, `SECURITY.md`, and the relevant ADRs.
2. Create or select one issue with explicit acceptance criteria.
3. Add tests for success, malformed input, denied access, and failure paths.
4. Run the repository verification commands from `README.md`.
5. Update setup or architecture documentation when behavior changes.
6. Submit a focused pull request using the template.

Never include credentials or personal device data in fixtures, logs, screenshots,
commits, or issue reports.

Commit subjects should use a conventional prefix, for example:

```text
feat(hub): add authenticated system status tool
test(protocol): reject unsupported message versions
docs(security): document LAN threat boundary
```
