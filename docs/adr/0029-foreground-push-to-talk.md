# ADR 0029: Foreground Push-To-Talk Voice Input

## Status

Accepted

## Context

GOFFY needs Jarvis-like voice entry, but always-listening wake words and
background microphone capture are outside the current safety and battery budget
for a Moto G-class phone. Android already provides `SpeechRecognizer`, which can
run as a foreground, user-initiated recognition session without adding a bundled
large speech model.

## Decision

GOFFY adds `RECORD_AUDIO` only for visible push-to-talk command capture. The MIC
button requests runtime permission when needed, starts one foreground
`SpeechRecognizer` session, requests offline recognition when available,
sanitizes recognized text, and fills the command box for user review. It does not
auto-submit the command. Recognition is canceled when the Activity stops.

The ROM system-app descriptor remains non-privileged, keeps
`privileged_permission_allowlist` empty, and declares `RECORD_AUDIO` as
`foreground_user_approved_only`.

## Consequences

- No background recording, wake-word listener, or microphone service is added.
- The actual speech provider may still decide whether offline recognition is
  available; GOFFY discloses that it only requests offline recognition.
- The command review step preserves the existing deterministic routing and
  approval boundary before any tool invocation.
