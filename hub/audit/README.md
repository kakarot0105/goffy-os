# Hub Audit

Direct Hub and MCP operator audit is deferred in this milestone.

The only persisted audit slice today is the Android-local, user-visible
terminal-task history described in [`docs/adr/0011-redacted-android-audit-trail.md`](../../docs/adr/0011-redacted-android-audit-trail.md).
Hub and MCP still emit transient typed progress, result, and verification
events, but the Hub does not durably retain operator or task history yet.

That Hub-side work stays blocked on two preconditions:

- Stable paired identity for both the Android device and the direct Hub/MCP operator
- User-visible retrieval on Android so retained records remain inspectable

Until those exist, GOFFY does not add a second audit store for direct Hub/MCP
activity here.
