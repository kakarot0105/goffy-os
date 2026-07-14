# Android Setup

## Required tools

- Android Studio compatible with Android Gradle Plugin 9.2
- JDK 17
- Android SDK Platform 36 and Build Tools 36.0.0

Open the `android/` directory in Android Studio and allow Gradle sync to finish.
The app supports API 26 and newer and starts in GOFFY LITE mode.

From the repository root, run the pinned Gradle wrapper:

```bash
python3 scripts/android_preflight.py
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease --no-daemon
python3 scripts/security_scan.py --require-merged-manifests
```

The preflight performs no shell execution. It inspects `JAVA_HOME`, known JDK
locations, `ANDROID_HOME` or `ANDROID_SDK_ROOT`, SDK component directories,
`adb`, and `android/gradlew`. Fix any failed preflight item before treating a
Gradle failure as an app regression.

The debug APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`.
The first wrapper run downloads Gradle 9.4.1 and validates the distribution
checksum. Verify the wrapper JAR checksum separately before replacing it, and
review both published checksums during any wrapper upgrade.

## Current slice behavior

- Supported commands are the exact `Show/Check [me] my Mac status` family with
  normalized whitespace and optional trailing `.`, `!`, or `?`.
- Battery commands such as `Show my battery status` and `What's my phone battery
  level?` run entirely on PHONE without a Hub link.
- Device commands such as `Show my phone info` and `What phone is this?` return
  only manufacturer, model, Android release, and SDK level on PHONE.
- `Create a note saying Buy milk` creates an app-private note only after a visible
  `Approve once` action. The approval expires after 60 seconds and is bound to the
  exact task, tool, note text, and deadline.
- Denying, cancelling, or allowing approval to expire invokes no phone tool. A
  successful note task means the inserted SQLite row was re-read and matched.
- `Set a timer for 5 minutes` supports one numeric seconds, minutes, or hours
  duration from 1 second through 24 hours. Approval dispatches the exact duration
  to an allowlisted, enabled, exported system Clock app and displays its package.
- The timer output records that GOFFY requested `EXTRA_SKIP_UI=true`; it does not
  claim the Clock honored that request. The task ends `UNVERIFIED` because another
  app's timer state is not readable.
- Timer creation adds only Android's normal `SET_ALARM` permission. GOFFY runs no
  countdown service, notification loop, exact alarm, or background receiver.
- `Turn on the flashlight` and `Turn off the torch` require visible one-time
  approval. GOFFY uses `CameraManager.setTorchMode` without opening the camera and
  reaches `VERIFIED` only after a matching callback.
- The flashlight declares flash hardware optional and never requests or uses the
  QR scanner's `CAMERA` permission. Its callback is removed on every success,
  failure, timeout, or cancel.
- Any extra instruction, unrelated command, or appended authority is rejected on
  the phone before a Hub connection opens.
- Before a Mac invocation, Android requests only the locally routed capability on
  the same authenticated socket. It sends no invocation until tool version,
  target, permission, schemas, and safety annotations are compatible.
- Missing or incompatible discovery ends the task without `Ready`, progress, or
  tool execution. The timeline records when capability compatibility succeeds.
- Android treats `ToolResult` as data only. The task becomes successful only
  after a matching `VerificationResult`.
- Battery status reads `BatteryManager` once per command, validates `0..100`,
  requests no permission, and performs no polling or background work.
- Device info reads static `Build` display fields once, requests no permission,
  and excludes identifiers such as serial, IMEI, Android ID, MAC, and fingerprint.
- Automatic reconnect is bounded to discovery and connection failures before the
  invocation is sent: at most 2 retries and 3 total attempts. After send, the
  client does not replay the request. A complete attempt times out after 35 seconds.
- Cancel only stops the local job and socket. Hub-side completion is not
  guaranteed.
- Cancelling a pending note approval guarantees no tool invocation. Once the
  approved SQLite transaction starts, cancellation is requested but rollback is
  not guaranteed; the timeline states that limitation rather than claiming success.
- A paired bearer is returned once through foreground loopback redemption, stored
  as one bounded Android Keystore AES-GCM record under `noBackupFilesDir`, and
  activated only after read-back verification. Challenge/token material is not
  placed in URLs, saved Compose state, audit rows, or stringified output.
- Corrupt or undecryptable paired state is removed and visibly disables Mac
  authority. Restore performs no network probe, polling, or background repair.
- Pairing is canceled when the Activity leaves the foreground; any local partial
  record is removed after the enrollment job finishes, with no automatic retry.
- `Forget link` deletes the phone copy and key after joining any canceled
  enrollment. Paired links then make one loopback self-revocation request to the
  Hub. The UI reports whether Hub revocation was verified or remains unverified.
  If local credential deletion itself cannot be verified, GOFFY enters a degraded
  state and tells the operator to clear app data before relaunching.
- `Rotate token` is available only for paired links. It requires a visible
  confirmation, cancels active work, makes one loopback rotation request, saves
  the new bearer only after encrypted read-back verification, and disables Mac
  access with a re-pair instruction if Hub rotation or local persistence is
  ambiguous.
- Pairing QR scanning is foreground-only. Tapping `Scan QR` requests the normal
  Android camera permission if needed, opens a visible scanner panel, decodes QR
  codes only, stores no image, and closes the camera when the panel is dismissed,
  the Activity stops, or one bundle is captured. Scanning only fills the existing
  pairing-bundle field; the user still must tap `Pair phone`.
- Manual development bearer entry remains debug-only and memory-only.

## Android audit trail

Android persists terminal task history in the same visible timeline.

- Storage is app-private SQLite only. Android backup and device transfer are
  disabled for the app, and uninstall removes the records.
- Retention is bounded to the newest 50 terminal records.
- Each record stores only closed metadata: audit schema/protocol versions, task
  UUID and time, source, PHONE/MAC target, allowlisted tool or `null`,
  SAFE/CONFIRM permission or `null`, terminal phase, approval outcome, and
  bounded event kinds.
- The audit never stores raw command text, typed arguments, note text, row IDs,
  tool results, device info, approval text, event messages, endpoint or token
  values, free-form summaries, or verification checks.
- Restore is display-only. Relaunch may show terminal cards, but never a
  structured result, pending approval, active task, or execution authority.
- Writes happen only after `VERIFIED`, `UNVERIFIED`, `FAILED`, or `CANCELLED`.
  Killing the process mid-task creates no synthetic success row.
- Read or write failure flips the badge to `AUDIT / DEGRADED ...` and may leave
  affected history in memory only. Corrupt rows are discarded while valid rows
  are still restored and the badge shows the discarded-row count. GOFFY does
  not rewrite the original execution verdict and schedules no background retry.

Performance assessment: the audit path is a tiny bounded SQLite read at startup
and one write per terminal task on the existing IO dispatcher. There is no
polling or WorkManager, so this slice stays within GOFFY LITE expectations for
4 GB devices. Paired restore adds one bounded file read and Keystore decrypt; pair
and forget add one tiny atomic write/delete. QR scanning lazy-loads CameraX and
the bundled barcode model only while the visible scanner panel is active, uses a
single latest-frame analyzer at 1280x720, and shuts down the analyzer when closed.
No large model or background service loads.

## Local verification

Run the unified verifier before relying on an Android change:

```bash
.venv/bin/python scripts/verify_all.py
```

The verifier runs the Python/Hub checks, then Android preflight. If the JDK,
Android SDK, Build Tools, and `adb` are present, it continues into Gradle lint,
unit tests, debug/release assembly, and post-build merged-manifest security
validation. On a machine without Android tooling, use `--allow-missing-android`
only to verify non-Android work while keeping the Android blocker visible in the
report.

If the local environment is not ready, run the read-only setup doctor for a
grouped human report or JSON that can be attached to an issue:

```bash
.venv/bin/python scripts/setup_doctor.py
.venv/bin/python scripts/setup_doctor.py --json
.venv/bin/python scripts/setup_doctor.py --include-device
```

The doctor redacts repo, home, and absolute toolchain paths, but review output
before posting it to a public issue.
`--include-device` adds read-only `adb devices -l` and `adb reverse --list`
diagnostics. It reports whether an authorized device is connected and whether
`tcp:8787` is reversed, but it does not run shell commands on the phone and does
not print device serials.

Android CI runs the same setup doctor with
`--android-only --include-device --json` only after an Android gate fails. The
diagnostic step is non-blocking and appears after the blocking preflight, Gradle,
and merged-manifest checks so it cannot hide or weaken the original validation
result.

Before starting a Moto G physical validation pass, run the readiness verifier:

```bash
.venv/bin/python scripts/verify_moto_g_readiness.py
.venv/bin/python scripts/verify_moto_g_readiness.py --json
.venv/bin/python scripts/guide_moto_g_validation.py
.venv/bin/python scripts/guide_moto_g_validation.py --json
.venv/bin/python scripts/run_moto_g_validation_pipeline.py
.venv/bin/python scripts/run_moto_g_validation_pipeline.py --json
.venv/bin/python scripts/collect_moto_g_validation_bundle.py
.venv/bin/python scripts/collect_moto_g_validation_bundle.py --json
.venv/bin/python scripts/verify_moto_g_validation_bundle.py .goffy-validation/<bundle>
.venv/bin/python scripts/verify_moto_g_validation_bundle.py .goffy-validation/<bundle> --json
```

It combines Android preflight, read-only device diagnostics, fixed localhost Hub
`/health`, and debug APK presence into one report. It does not run `adb shell`,
configure `adb reverse`, install the APK, start the Hub, or replace the manual
phone checklist below.
The guide adds the USB setup state, bounded manual checklist status, and the next
safe action to take. It does not execute the USB setup command or control the
phone UI. The bundle collector writes local `.goffy-validation/moto-g-...`
artifacts containing guide, smoke, and manifest JSON/text plus SHA-256 hashes for
evidence artifacts. It is read-only for the phone and refuses to overwrite a
timestamped bundle unless `--force` is passed against a previously marked GOFFY
validation bundle directory. The verifier checks manifest schema, safe relative
paths, artifact hashes, metadata marker presence, and guide/smoke consistency
without touching the phone. Verifier exit codes are: `0` for integrity-valid
passed physical smoke evidence, `1` for integrity-valid but incomplete physical
smoke evidence, and `2` for schema or integrity failure.
The pipeline command is the preferred operator path because it collects and
verifies the bundle in one local, phone-read-only step. It still re-runs the same
fixed readiness probes inherited from the collector/recorder path:
`GET http://127.0.0.1:8787/health`, `adb devices -l`, and `adb reverse --list`.
It does not run `adb shell`, configure `adb reverse`, install the APK, or broaden
network access beyond localhost. Pipeline exit code `2` can also mean collection
failed before verification, such as an existing bundle or unsafe `--force`
target.

When the readiness report has no blockers except a missing Hub USB reverse, use
the USB setup runner. It prints the fixed setup plan by default:

```bash
.venv/bin/python scripts/run_moto_g_usb_setup.py
.venv/bin/python scripts/run_moto_g_usb_setup.py --json
```

To actually mutate the connected phone, both flags are required:

```bash
.venv/bin/python scripts/run_moto_g_usb_setup.py --execute --confirm-device-mutation
```

Execution runs only `adb reverse tcp:8787 tcp:8787`, verifies the reverse, and
then runs `adb install -r` against the debug APK. It never runs `adb shell`,
launches the app, taps the UI, types `Show my Mac status`, starts the Hub, or
broadens the ADB command surface.
Mutating mode uses only the Android SDK `platform-tools/adb` resolved from the
configured SDK root and only installs the debug APK from this checked-out GOFFY
repository. PATH `adb` and alternate `--repo-root` values remain plan-only.

After the manual phone checks pass, record redacted evidence:

```bash
.venv/bin/python scripts/record_moto_g_smoke.py \
  --app-launched pass \
  --command-submitted pass \
  --mac-status-displayed pass \
  --timeline-recorded pass \
  --restart-restored pass \
  --json
```

To package the same evidence for review:

```bash
.venv/bin/python scripts/run_moto_g_validation_pipeline.py \
  --app-launched pass \
  --command-submitted pass \
  --mac-status-displayed pass \
  --timeline-recorded pass \
  --restart-restored pass
```

The recorder is read-only. It captures readiness, USB setup state, the debug APK
hash, and bounded operator-entered checklist results. It runs only fixed
readiness probes plus read-only `adb devices -l` and `adb reverse --list`
through the SDK `platform-tools/adb`. It never runs `adb shell`, never mutates
the phone, never launches GOFFY, never performs UI automation, never executes
arbitrary commands, and never accepts free-form notes.

## USB localhost debug flow

1. Start the Hub on the Mac in either legacy development mode or the paired mode
   documented in [Hub setup](hub.md). Paired mode is recommended for restart tests.

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   export GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token'
   .venv/bin/goffy-hub
   ```

2. On the Moto G, enable Developer options and USB debugging, then connect the
   device by USB and approve only the computer fingerprint you recognize.
3. Reverse the Hub port from the host to the phone manually or by using the USB
   setup runner above:

   ```bash
   adb reverse tcp:8787 tcp:8787
   ```

   Verify the host-side device link with:

   ```bash
   .venv/bin/python scripts/setup_doctor.py --include-device
   ```

4. Install the debug app from Android Studio, the USB setup runner, or the debug
   APK, then launch it manually on the phone.
5. For paired mode, create a pairing QR SVG on the Mac:

   ```bash
   GOFFY_HUB_TOKEN='replace-with-the-same-bootstrap-token' \
     .venv/bin/python scripts/create_pairing_qr.py --output goffy-pairing-bundle.svg --force
   open goffy-pairing-bundle.svg
   ```

   Scan it with `Scan QR`, then tap `Pair phone` within 120 seconds. The SVG is a
   short-lived secret; delete it after pairing. Do not redeem the embedded
   challenge elsewhere or use a cloud-synchronized clipboard. For legacy mode,
   enter the development bearer in the debug-only field.
6. Submit `Show my Mac status` or `Check my Mac status`, restart the app, and run
   it again without re-entering the paired bearer.
7. Run `scripts/record_moto_g_smoke.py` with the checklist flags above and attach
   the JSON output to the validation notes.

The task timeline should show an authenticated compatible MAC capability before
accepted tool progress. A Hub using GOFFY protocol `0.1.0`, a missing tool, or a
changed tool contract must fail before invocation rather than silently falling back.

Debug cleartext is allowed only for `localhost` and `127.0.0.1` through the
debug network security config. Release builds should use `wss://.../ws/v1`.
LAN use is still unsupported until trusted certificate onboarding and guided
device pairing exist.

## Physical-device status

The USB localhost flow is implemented in software, but the full physical Moto G
verification pass is still incomplete. Do not treat Milestone 1 as hardware
verified yet.

For the pairing slice, verify that restart restores `PAIRED`, an expired or
altered challenge saves nothing, and `Forget link` first shows an explicit
confirmation. With the Hub reachable over `adb reverse`, confirm the app reports
verified Hub revocation and remains unpaired after a second restart. Then list
credentials on the Mac and confirm that credential has a revocation timestamp. Run
one offline pass with the Hub stopped: the app should still remove local authority
and report remote revocation as unverified. Record the Moto G Android version and
any Keystore, self-revocation, or OEM process-restart failure.

For the token-rotation slice, pair the phone, start a Mac status task, then tap
`Rotate token` and confirm. The active task should cancel locally, the link should
return to `PAIRED`, and the setup card should show a non-warning rotation notice.
Run `Show my Mac status` again to verify the new bearer works. Then restart the
app and confirm the paired link restores without re-entering a bearer. Finally,
force one failure by stopping the Hub before rotation; GOFFY should mark the link
degraded, disable Mac access, and require re-pairing rather than silently using a
possibly stale token.

For the QR transfer path, first deny the camera permission and confirm pairing is
not attempted and the setup card tells you to paste the bundle instead. Then grant
permission, scan a current Hub bundle QR, confirm the scanner panel closes, the
masked bundle field is populated, and no credential is issued until `Pair phone`
is tapped. Close the scanner without scanning and confirm no bundle field change.
Put the app in the background while the scanner is visible and confirm the camera
indicator turns off and no background capture continues. Repeat with a non-GOFFY
QR and confirm pairing still fails through the existing typed bundle parser.

The battery slice is also software-verified only. On a device, run the app
without configuring a Hub, submit `Show my battery status`, and confirm the
timeline shows `PHONE / phone.battery.status / SAFE`, the percentage and charging
state, and a final `VERIFIED` phase without any permission prompt.

Then submit `Show my phone info` and confirm the timeline shows
`PHONE / phone.device.info / SAFE`, only the four documented fields, and a final
`VERIFIED` phase without a Hub connection or permission prompt.

Finally, submit `Create a note saying Buy milk` and confirm the timeline shows
`PHONE / phone.note.create / CONFIRM` and `AWAITING APPROVAL`. Verify all of these:

1. Tap `Deny`; the task becomes `CANCELLED` and explicitly states no tool ran.
2. Submit it again and wait 60 seconds; it becomes `FAILED` without a tool event.
3. Submit it again and tap `Approve once`; progress appears, the note text is
   displayed, and the task reaches `VERIFIED` only after the database re-read.
4. Tap approval controls repeatedly; no second note is created for the same task.

The database is internal to the app and requires no storage permission. App
uninstall removes it. There is no note browser or delete control yet, so use only
non-sensitive test text during pre-alpha device verification.

Then submit `Set a timer for 1 minute`. Confirm `PHONE / phone.timer.create /
CONFIRM`, deny once and verify Clock does not open, then approve a new request.
GOFFY should request no intermediate Clock confirmation screen and name the Clock
package in its dispatch receipt. The task must end `UNVERIFIED`, not claim that the
timer exists. Record whether the OEM Clock showed UI and whether the timer rang,
then dismiss it in the Clock app. This behavior is not yet verified on the Moto G.

Then submit `Turn on the flashlight`. Confirm `PHONE / phone.flashlight.set /
CONFIRM`, deny once and verify the light stays unchanged, then approve a new
request. The task should reach `VERIFIED` only after the rear torch turns on.
Submit `Turn off the torch`, approve it, and confirm a second `VERIFIED` result.
If `CAMERA` was not previously granted for QR pairing, the flashlight action
should not request it. No camera privacy indicator or image preview should
appear. Record failures when another camera app is active. Physical Moto G
verification remains open.

For the audit trail, complete one restart pass on a real device:

1. Produce at least one terminal PHONE record and, if a Hub is configured, one terminal MAC record.
2. Confirm the badge shows `AUDIT / READY / 50 MAX`.
3. Force-stop the app or reboot the phone, relaunch GOFFY, and confirm the newest terminal cards reappear as redacted history entries with target/tool/permission/phase and the audit timestamp.
4. Confirm restored cards are display-only: no structured result body, no pending approval controls, no active task, and no way to resume or replay authority from history.
5. Start a new approval-gated task, kill the app before it reaches a terminal phase, relaunch, and confirm there is no synthetic success row and no resumed approval.
6. If the badge reports `AUDIT / DEGRADED ...`, treat the stored history as partial and confirm GOFFY still does not alter the already shown execution verdict or schedule background retry work.
