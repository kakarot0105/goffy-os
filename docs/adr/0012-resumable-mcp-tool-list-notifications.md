# ADR 0012: Resumable MCP tool-list notifications

- Status: Accepted
- Date: 2026-07-13

## Context

Health-aware MCP discovery already removes and restores unavailable tools, but
clients had to poll `tools/list`. A live notification stream alone is not enough:
a disconnect between a health transition and the next list request can hide the
signal. A shared SDK event store is also unsafe because standalone GET events use
the same stream key in every MCP session, which could permit cross-session replay.

## Decision

- Advertise `tools.listChanged=true` and use the SDK `ServerSession` API to send
  standard `notifications/tools/list_changed` messages after health transitions.
- Register a session for notifications when its initialized client first calls
  `tools/list`. Register before reading the list so a concurrent transition is
  either reflected in the response or followed by a notification.
- Enable authenticated Streamable HTTP GET at exact `/mcp`. Retain the existing
  bearer, Host, Origin, protocol-version, session-ID, and SDK credential-owner
  checks. Keep one standalone GET stream per session.
- Give every new MCP session a distinct in-memory event store. Cursor IDs include
  a random per-session prefix and cannot be used in another session.
- Retain only standalone GET priming cursors and empty tool-list change
  notifications. Never retain tool calls, arguments, results, errors, resources,
  prompts, or arbitrary server messages.
- Cap each store at 64 events and 16 KiB, evicting oldest entries. An unknown,
  foreign, or evicted cursor receives no retained history, only a new empty
  re-list signal before attaching to the current session's live tail.
- Bound each per-session notification send to one second. A closed or stalled
  session is removed from the notifier without blocking other sessions or
  changing registry health.
- Pause session idle expiry only while its authenticated GET stream is connected,
  keep that stream inside active-session accounting, and rotate the connection
  after 45 seconds. Explicit termination, post-disconnect idle expiry, or Hub
  restart destroys the transport and its replay store.
- Keep Android `/ws/v1` discovery behavior unchanged. The phone discovers before
  each invocation and does not gain a background poller or event stream.

## Consequences

Compatible MCP clients receive a lightweight signal instead of polling and can
recover notifications missed during an ordinary GET disconnect. The signal has
no tool names or state; clients must call `tools/list` to obtain current truth.
Memory and fan-out remain bounded by the active-session limit and per-session
caps, with no disk writes or sensitive replay payloads.

Replay does not survive session termination, idle expiry, or Hub restart. The
pinned SDK also documents a narrow replay-to-live-tail ordering window while it
re-registers a resumed stream. GOFFY bounds that risk by priming fresh streams,
sending a re-list signal whenever a reconnect replays or cannot resolve its
cursor, and rotating streams every 45 seconds. A transition stored in that window
is therefore recovered on the next bounded reconnect. Tests cover live delivery,
disconnect replay, stale-cursor recovery, and active-stream idle behavior.
Removing the SDK-level window entirely would require owning more of the transport
and is deferred until evidence justifies it.

## Rejected alternatives

- Share one event store across SDK transports. Standalone stream keys are not
  session-qualified, so this risks cross-session replay.
- Persist replay events to SQLite. List-change notifications contain no durable
  state, and persistent cursors would require stable paired identity and a
  revocation model that GOFFY does not yet have.
- Store every SDK event. Tool results and future server messages may be sensitive;
  resumable list invalidation does not require them.
- Add a custom Android notification channel or polling loop. Android already
  performs invocation-scoped discovery and should remain battery-conscious.
- Disable idle expiry whenever a session has ever opened GET. Only an actively
  connected, authenticated stream pauses the timer.

## References

- [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
