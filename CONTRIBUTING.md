# Contributing to GOFFY OS

GOFFY OS is pre-alpha. Keep changes narrow, testable, and easy to review.

1. Read `AGENTS.md`, `SECURITY.md`, and the relevant ADRs.
2. Create or select one issue with explicit acceptance criteria.
3. Search for existing open-source implementations before writing new feature
   code. Prefer reuse when the license, security posture, maintenance state,
   dependency weight, and old-phone performance profile are acceptable.
4. Document any borrowed code, source project, license, local modifications, and
   why vendoring or depending on it is safe for GOFFY.
5. Add tests for success, malformed input, denied access, and failure paths.
6. Run `.venv/bin/python scripts/verify_all.py`. If Android tooling is not
   installed, use `--allow-missing-android` only for non-Android changes and
   state that limitation clearly.
7. Update setup or architecture documentation when behavior changes.
8. Submit a focused pull request using the template.

Never include credentials or personal device data in fixtures, logs, screenshots,
commits, or issue reports.

Commit subjects should use a conventional prefix, for example:

```text
feat(hub): add authenticated system status tool
test(protocol): reject unsupported message versions
docs(security): document LAN threat boundary
```
