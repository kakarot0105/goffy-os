# Hub Setup

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token'
.venv/bin/goffy-hub
```

`GET /health` is intentionally unauthenticated and returns no private host data.
It reports `degraded` when any registered tool is unavailable and includes
healthy/unavailable counts plus a registry revision, but no names or probe details.
`/ws/v1` requires `Authorization: Bearer <token>`. Without paired mode, the
bootstrap token is the legacy SAFE-tool credential; if it is absent, every
WebSocket and MCP tool request is rejected. Each Android
Mac task opens its own authenticated WebSocket, sends a
`CapabilityDiscoveryRequest` for the locally routed tool, validates the response,
then sends one `ToolInvocation`. The Hub consumes that discovery on the invocation
attempt and emits `ToolProgress`, `ToolResult`, and `VerificationResult` or a
terminal `ToolError`.

GOFFY protocol `0.2.0` is required on both sides. Discovery records use MCP
`2025-11-25` tool fields and JSON Schema 2020-12, but `/ws/v1` is not an MCP
JSON-RPC endpoint. Do not connect a generic MCP client to this path.

## Local paired-device mode

Paired mode is opt-in and currently operator-driven. Configure an absolute state
path outside the repository before starting the Hub:

```bash
state_dir="$HOME/Library/Application Support/GOFFY Hub"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
export GOFFY_PAIRING_DATABASE_PATH="$state_dir/credentials.sqlite3"
export GOFFY_HUB_TOKEN='replace-with-a-long-random-bootstrap-token'
.venv/bin/goffy-hub
```

The Hub creates the database with mode `0600`. It stores only bearer digests and
bounded metadata. The configured bootstrap token now has pairing-admin scope only;
it cannot call `/ws/v1` or `/mcp`.

The Hub also creates `hub-identity.json` in the same state directory with
owner-only permissions. This file contains local identity material used to derive
a stable fingerprint included in USB-loopback pairing bundles and pinned by
Android paired credential storage. Inspect the public identity from the Mac only
through loopback bootstrap administration:

```bash
curl -fsS -H "Authorization: Bearer $GOFFY_HUB_TOKEN" \
  http://127.0.0.1:8787/admin/v1/hub-identity
```

The response is no-store and contains `schemaVersion`, `hubId`, `fingerprint`,
`createdAt`, `verifiedBy`, and `trustedLanSupported=false`. It does not expose
the private identity seed and does not mean LAN trust or certificate pinning is
ready. QR pairing bundles and redemption success responses contain the same
public identity fields; an Android client must reject bundles that omit them or
redemption responses that do not match them.

Before using a physical phone, run the in-process smoke verifier. It creates a
temporary local Hub app, mints a bundle, validates the QR payload, redeems the
challenge once, verifies replay rejection, rotates the paired bearer, confirms
the old bearer fails and the new bearer authenticates, and confirms admin listing
does not echo pairing material:

```bash
.venv/bin/python scripts/verify_pairing_flow.py
```

From the same Mac, create one 120-second QR-ready pairing bundle and write it as
a local SVG QR code:

```bash
GOFFY_HUB_TOKEN='replace-with-the-same-bootstrap-token' \
  .venv/bin/python scripts/create_pairing_qr.py --output goffy-pairing-bundle.svg --force
```

The script accepts only an HTTP loopback Hub URL, posts the bootstrap token in an
`Authorization` header, validates the returned bundle shape, and writes the SVG
with owner-only file permissions. The SVG is a short-lived secret because it
contains the pairing token encoded in the QR modules; delete it after pairing.
Do not put the SVG or underlying bundle in source control, logs, command-line
arguments, cloud-synchronized clipboards, or screenshots. The documented default
filename is ignored by git, and the security scan rejects generated QR SVGs.

```bash
adb reverse tcp:8787 tcp:8787
open goffy-pairing-bundle.svg
```

In the debug app, keep `ws://127.0.0.1:8787/ws/v1`, tap `Scan QR`, scan the SVG
from the Mac screen, and tap `Pair phone` before the 120-second expiry. This
temporary operator-assisted transfer is intentionally not a production onboarding
flow. Android verifies the bundle version, loopback identity metadata, and exact
endpoint match before posting the typed redemption once. It then encrypts the
returned bearer with Android Keystore, verifies the stored record, and shows the
link as paired.

Manual JSON transfer remains possible for low-level administration:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $GOFFY_HUB_TOKEN" \
  http://127.0.0.1:8787/admin/v1/pairing/bundles
```

The bundle contains `bundleVersion`, the exact loopback `hubEndpoint`, explicit
`usb_loopback` Hub identity metadata, and one redeemable challenge. The identity
metadata says the bundle was created through the loopback bootstrap-admin session;
it is not LAN trust, certificate pinning, or production remote onboarding. Do not
redeem the same challenge elsewhere first: it is single-use.

The older `/admin/v1/pairing/challenges` route remains available for Hub
compatibility tests and low-level administration, but Android onboarding now
targets the bundle route.

`deviceId` is descriptive setup metadata; the returned `credentialId` is the
security principal. List credentials or perform administrator revocation with the
bootstrap token:

```bash
curl -fsS -H "Authorization: Bearer $GOFFY_HUB_TOKEN" \
  http://127.0.0.1:8787/admin/v1/credentials
curl -fsS -X DELETE -H "Authorization: Bearer $GOFFY_HUB_TOKEN" \
  http://127.0.0.1:8787/admin/v1/credentials/REPLACE_WITH_CREDENTIAL_ID
```

Revocation closes indexed live WebSocket and MCP sessions before success is
returned and survives Hub restart. Pending challenges are memory-only and do not.
Android's `Forget link` deletes its encrypted copy and key first, then calls the
paired self-revocation route once when the link is paired. A verified response
means the Hub revoked that exact authenticated credential. If the phone reports
remote revocation as unverified, or if the phone is lost, use the administrator
route above from the Mac and inspect the credential list.

Paired credentials can also rotate their own bearer over loopback without
creating a second device identity:

```bash
curl -fsS -X POST -H "Authorization: Bearer $GOFFY_PAIRED_ACCESS_TOKEN" \
  http://127.0.0.1:8787/pairing/v1/rotate
```

The Hub derives the credential ID from the authenticated paired bearer, atomically
replaces the stored digest only if that bearer is still current, returns the same
credential ID plus a new one-time bearer, and closes all indexed WebSocket and
MCP sessions for that credential. The old bearer fails new authentication after a
verified rotation response. Store the new bearer immediately; do not retry a
rotation conflict automatically because another successful rotation may already
have changed Hub state.
Paired mode requires a local Hub bind, and all pairing and administration routes
also reject non-loopback clients. Configured LAN TLS and allowlists do not override
these guards. Android exposes manual confirmed token rotation for paired links;
it also shows a foreground reminder when the current paired bearer issue time is
older than the local policy threshold. Automatic rotation schedules and trusted
LAN onboarding are not implemented yet.

## MCP client

Exact `/mcp` supports MCP `2025-11-25` initialization, `tools/list`, and
`tools/call` through the official Python SDK. It returns JSON and requires the
session ID issued during initialization for subsequent operations. Authenticated
`GET` opens the session's MCP event stream, and `DELETE` terminates the session.
Disconnected event streams resume with `Last-Event-ID`; an active stream pauses
the 60-second idle timer while remaining inside the active-session cap. The Hub
rotates each stream after 45 seconds so clients reconnect through the bounded
replay path. Run the Hub, then use the repository's official-client demo:

```bash
GOFFY_HUB_TOKEN='replace-with-the-same-development-token' \
  .venv/bin/python scripts/demo_mcp.py
```

The demo succeeds only after negotiating the expected protocol, discovering the
default SAFE Mac tools, calling one typed tool with bounded arguments, and
validating the structured output. It never prints the token.

The local MCP Host and Origin allowlists are derived from port `8787`. Override
them only with exact comma-separated values:

```bash
export GOFFY_MCP_ALLOWED_HOSTS='127.0.0.1:8787,localhost:8787'
export GOFFY_MCP_ALLOWED_ORIGINS='http://127.0.0.1:8787,http://localhost:8787'
export GOFFY_MCP_MAX_CONCURRENT_CALLS='2'
export GOFFY_MCP_MAX_ACTIVE_SESSIONS='8'
export GOFFY_OPERATOR_AUDIT_MAX_EVENTS='256'
export GOFFY_TOOL_HEALTH_TIMEOUT_SECONDS='1'
export GOFFY_TOOL_HEALTH_INTERVAL_SECONDS='30'
```

Wildcards are rejected. A native MCP client usually sends no `Origin`; if it does,
the value must match exactly. Non-local binding additionally requires explicit
LAN mode, TLS files, and `GOFFY_MCP_ALLOWED_HOSTS`. These checks do not make LAN
operation production-ready: pairing delivery remains loopback-only, and trusted
certificate provisioning plus the MCP authorization profile are still absent.

The Hub seals the registry and completes one health pass before accepting traffic.
It then checks only compiled local probes at the configured interval, with a
five-second hard configuration maximum and four-probe concurrency cap. Unhealthy
tools disappear from `/ws/v1` discovery and MCP `tools/list`; calls fail with the
same generic unknown-or-unauthorized error. Recovery restores the original typed
definition. Android discovers before every Mac invocation, while MCP clients must
explicitly re-run `tools/list` after `notifications/tools/list_changed`. The Hub
keeps only those empty notifications in a random, per-session in-memory replay
store capped at 64 events and 16 KiB. It does not retain tool results, share
cursors between sessions, or replay across termination, idle expiry, or Hub
restart. Unknown, foreign, and evicted cursors replay no retained history; they
receive a fresh re-list signal and attach to the current session's live tail. No
network health probe or busy polling is used by the current default Mac tools.

## Mac Process List

`mac.processes.list` is enabled by default on macOS Hub hosts as a SAFE,
read-only metadata tool. Non-macOS hosts do not register it. It uses `psutil`
directly, not shell commands. Tool input accepts only `maxEntries`, bounded from
1 through 25. Output contains bounded process count, skipped count, truncation
state, and entries with PID, process-name basename, status, RSS memory, and
optional start time. It deliberately omits command lines, executable paths,
environment variables, open files, network connections, current working
directories, and user names.

Health checks call only a lightweight `psutil.boot_time()` availability probe and
do not enumerate processes; off-macOS checks fail closed. Android can invoke the exact
`What's running on my Mac`, `What is running on my Mac`,
`Show my Mac processes`, `List my Mac processes`, or
`Check me my Mac processes` routes after discovery shows this tool healthy;
Android TTS reports counts without reading process names aloud.

## Approved Mac File Roots

`mac.files.list` and `mac.files.largest` are disabled by default. Enable them
only for directories the operator is comfortable exposing through SAFE,
read-only metadata:

```bash
export GOFFY_MAC_FILES_ROOTS="$HOME/Documents/GitHub,$HOME/Desktop/goffy-lab"
```

Each entry must be an existing absolute directory. The Hub resolves and dedupes
the roots at startup, registers the tool only when at least one root is
configured, and marks the tools unavailable if a configured root later
disappears. `mac.files.list` input uses `rootIndex`, `relativePath`,
`maxEntries`, and `includeHidden`. `mac.files.largest` also accepts a bounded
`maxDepth` and scans at most 5,000 entries before reporting truncation. Output
contains root indices/names, bounded relative metadata, and no absolute root
paths. Dotfiles are hidden by default, symlinks are reported or skipped without
following their targets, and traversal outside the approved root is rejected.
These tools do not read file contents, create files, move files, delete files,
or execute shell commands. Android currently invokes only the default approved
root through `List my Mac files`, `Show my Mac files`, or
`Find the largest files on my Mac`; root/path selection needs a separate UX and
policy review.

## Approved Mac App Catalog

`mac.apps.list` is disabled by default. Enable it only for applications the
operator is comfortable exposing as SAFE catalog metadata:

```bash
export GOFFY_MAC_APP_ALLOWLIST='Safari=com.apple.Safari,Terminal=com.apple.Terminal'
```

Each entry must use `Display Name=bundle.id`. The Hub registers the tool only
when at least one bounded, unique entry is configured. Output contains app
indices, display names, and reverse-DNS bundle identifiers only. This tool does
not scan `/Applications`, reveal app paths, launch apps, open files, or execute
shell commands. Android invokes it through `List my Mac apps`,
`Show my Mac applications`, or `What apps are approved on my Mac?`.

`mac.apps.open` is a separate CONFIRM tool and is disabled unless the catalog
allowlist is configured and app opening is explicitly enabled:

```bash
export GOFFY_MAC_APP_OPEN_ENABLED=true
```

When enabled, the Hub registers the CONFIRM tool but keeps it unavailable on the
current SAFE-only WebSocket and MCP transports. Android has the typed route and
approval UI scaffold for commands like `Open Safari on my Mac`, but a follow-up
protocol increment must add a Hub-validated, one-time approval artifact before
the Hub will execute the action end-to-end. The tool implementation is limited to
the configured display name, maps it to the fixed allowlisted bundle identifier,
uses `/usr/bin/open -b <bundle-id>` with a subprocess argument list, verifies the
app is running through a bounded Launch Services/AppleScript check, and does not
open files, scan installed app folders, interpolate shell strings, or expose
itself over the current SAFE-only MCP surface.

## Approved Git Repository Roots

`git.status` is disabled by default. Enable it only for repositories the
operator is comfortable exposing through SAFE, read-only status metadata:

```bash
export GOFFY_GIT_REPO_ROOTS="$HOME/Documents/GitHub/goffy-os,$HOME/Documents/GitHub/app-lab"
```

Each entry must be an existing absolute Git worktree root. The Hub resolves and
dedupes the roots at startup, registers the tool only when at least one root is
configured, and marks the tool unavailable if a configured root or `.git` marker
later disappears. Tool input uses `repoIndex`, `maxChanges`, and
`includeUntracked`. Output contains repo indices/names, branch metadata, bounded
status counts, bounded change paths, and no absolute repo roots. This tool uses
fixed `git status --porcelain=v2` arguments with `shell=False`; it does not read
file contents, produce diffs, fetch, commit, push, run tests, or execute
client-provided commands. Android currently invokes only the default approved
repo through `Show my git status` or `Check my git status`; repo selection needs
a separate UX and policy review.

## Approved Mac Clipboard Read

`mac.clipboard.read` is disabled by default. Enable it only when the operator is
comfortable exposing bounded plaintext clipboard contents through authenticated
SAFE Hub/MCP calls:

```bash
.venv/bin/pip install -e '.[clipboard]'
export GOFFY_MAC_CLIPBOARD_READ_ENABLED=true
```

The optional `clipboard` extra installs `pasteboard==0.4.0` on macOS. The Hub
registers `mac.clipboard.read` only when the environment flag is exactly `true`.
If the flag is enabled without a working provider, the Hub starts with the tool
unavailable and `/health` reports degraded instead of granting clipboard access.
Tool input uses `maxChars`, bounded to 1 through 2000. Output contains
`status`, `contentType=text`, bounded `text`, truncation flags, and bounded
character-count metadata. Empty or non-text clipboards return `status=empty`
with no text. Plaintext containing `file://` returns `status=unsupported` with
no text so file URLs are not exposed as copied strings.

Health checks call only the provider availability hook and never read clipboard
content. The tool reads on explicit invocation only, never writes the clipboard,
never polls in the background, never exposes binary formats or file URLs, and
does not create a generic Mac automation channel. Android can invoke only the
exact `Read my Mac clipboard` or `Show my Mac clipboard` routes after discovery
shows this tool healthy; MCP clients can use the tool after authenticated
`tools/list` shows it healthy. Android TTS does not read clipboard contents aloud.

Non-local binding requires `GOFFY_HUB_ALLOW_LAN=true` plus existing
`GOFFY_HUB_TLS_CERT_FILE` and `GOFFY_HUB_TLS_KEY_FILE` paths. This is a transport
guard, not trusted pairing transport. Configuring paired mode with a non-local
bind is rejected; trusted LAN use is still unsupported until certificate
onboarding exists, so localhost remains the recommended mode.

## Operator audit

In paired mode, the Hub keeps a bounded, hash-chained SQLite operator audit for
pairing, WebSocket, and MCP control-plane events. The file is
`operator-audit.sqlite3` beside the paired credential database and is created
with owner-only permissions. Retrieve the newest events from the Mac only
through loopback bootstrap administration:

```bash
curl -fsS -H "Authorization: Bearer $GOFFY_HUB_TOKEN" \
  'http://127.0.0.1:8787/admin/v1/audit/events?limit=20'
```

Paired phones can retrieve only their own credential-scoped audit events through
the loopback paired route:

```bash
curl -fsS -H "Authorization: Bearer $PAIRED_PHONE_TOKEN" \
  'http://127.0.0.1:8787/paired/v1/audit/events?limit=20'
```

The paired route does not expose bootstrap-admin events or other phones' events.

Responses are `no-store` and newest-first. The response includes `storageKind`
and `integrity`; paired mode should report `sqlite` plus `verified`,
`retention_gap`, or `tamper_detected`. Events contain only sequence, timestamp,
source, action, outcome, principal kind, optional credential ID, bounded detail
code, previous hash, and event hash. They do not contain bearer tokens, pairing
tokens, request bodies, command text, typed arguments, tool outputs, or
free-form summaries.

Keep `GOFFY_OPERATOR_AUDIT_MAX_EVENTS` bounded; the setting defaults to 256 and
is accepted only from 16 through 2048. Retention pruning can produce
`retention_gap`, which means the retained segment verifies but older pruned rows
are no longer available. The DB-local chain tip catches simple tail truncation,
but it does not protect against full database rollback or coordinated rewrite by
a local operator with filesystem access. Android retrieval, export, deletion,
and full forensic policy are not implemented yet.

## Android debug over USB

1. Start the Hub with `GOFFY_HUB_TOKEN` set.
2. Attach the Android phone by USB.
3. Reverse the Hub port:

   ```bash
   adb reverse tcp:8787 tcp:8787
   ```

4. In the debug app, configure `ws://127.0.0.1:8787/ws/v1`.
5. Run `Show my Mac status` or `Check my Mac status`.

The debug flow uses loopback cleartext only. Release builds should use
`wss://.../ws/v1`.

## Discovery and request shape

First send a `CapabilityDiscoveryRequest` envelope with
`{"toolName":"mac.system_info"}`. A compatible Hub returns one MCP-shaped tool
record correlated to the discovery message ID. Then send a `ToolInvocation`
envelope with the same tool name and an empty `arguments` object. The Hub emits
accepted progress, completed progress, `ToolResult`, and `VerificationResult`
with the invocation message ID as correlation ID.

Invocation before discovery, a second invocation without fresh discovery, or a
different tool name fails with `capability_discovery_required`. The shared
seven-envelope sequence is `protocol/fixtures/mac-system-info-flow.jsonl`.
