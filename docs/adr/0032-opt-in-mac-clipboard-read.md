# ADR 0032: Opt-In Mac Clipboard Read Tool

## Status

Accepted

## Context

Jarvis-like Mac assistance eventually needs clipboard awareness for explicit
requests such as "read my clipboard" or "summarize what I copied." The clipboard
is also a high-risk exfiltration surface because it often contains private text,
URLs, codes, or copied secrets. GOFFY policy blocks broad Mac automation and any
ambient background collection.

Reuse-first review:

- Pasteboard: https://github.com/tobywf/pasteboard, MPL-2.0, exposes Python
  bindings for AppKit NSPasteboard, supports Python 3.12, and avoids
  command-line clipboard helpers. It is macOS-only and marked beta/unsupported,
  so GOFFY keeps it optional rather than core.
- Pyperclip: https://github.com/asweigart/pyperclip, BSD-3-Clause, mature and
  cross-platform, but its macOS support can use `pbcopy` and `pbpaste` command
  helpers. That conflicts with the narrow-tool preference for this clipboard
  slice.
- Apple NSPasteboard:
  https://developer.apple.com/documentation/AppKit/NSPasteboard, the native
  macOS clipboard interface behind the selected optional provider.

## Decision

Add `mac.clipboard.read` as an optional SAFE Hub/MCP tool. It is registered only
when `GOFFY_MAC_CLIPBOARD_READ_ENABLED=true`. Real Mac clipboard access uses the
optional `pasteboard==0.4.0` extra and is not installed in the default runtime or
CI dependency set.

The tool accepts only `maxChars` from 1 through 2000. It returns plaintext only:
`status`, `contentType=text`, bounded `text`, `textTruncated`, `characterCount`,
and `characterCountTruncated`. Empty or non-text clipboards return
`status=empty` and no text. Plaintext containing `file://` returns
`status=unsupported` with no text so file URLs are not exposed as copied strings.
Health checks only ask whether the provider is available; they do not read
clipboard contents. The implementation does not write the clipboard, poll for
changes, expose binary formats, expose file URLs, or create a generic Mac
automation channel.

## Consequences

- Default Hub behavior is unchanged; no clipboard code runs unless explicitly
  enabled.
- MCP clients can call the tool after authenticated discovery shows it healthy.
- Android command routing is intentionally deferred so clipboard UX, approval,
  timeline wording, and speech handling can be reviewed separately.
- Future clipboard write, file URL, image, or history access requires separate
  schemas, permission classification, approvals, and verification behavior.
