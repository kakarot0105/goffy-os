## Outcome

Describe the user-visible behavior and the narrow issue addressed.

## Security and permissions

State execution target, permission level, side effects, timeout, and any new trust boundary.

## Verification

List exact commands and results. Include `.venv/bin/python scripts/verify_all.py`
or explain any explicit `--allow-missing-android` limitation, plus failure-path
tests and visible verification evidence.

## Checklist

- [ ] No arbitrary shell or command-string execution
- [ ] Inputs and outputs are typed and bounded
- [ ] Auth and permission checks fail closed
- [ ] Tests, lint, types, and security scan pass
- [ ] Documentation and roadmap are current
- [ ] No credentials or personal data are included
