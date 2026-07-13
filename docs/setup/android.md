# Android Setup

## Required tools

- Android Studio compatible with Android Gradle Plugin 9.2
- JDK 17
- Android SDK Platform 36 and Build Tools 36.0.0

Open the `android/` directory in Android Studio and allow Gradle sync to finish.
The app supports API 26 and newer and starts in GOFFY LITE mode.

From the repository root, run the pinned Gradle wrapper:

```bash
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease --no-daemon
python3 scripts/security_scan.py --require-merged-manifests
```

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
- The flashlight declares flash hardware optional and requests no `CAMERA`
  permission. Its callback is removed on every success, failure, timeout, or cancel.
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
- The bearer token is entered at runtime, sent only in the `Authorization`
  header, and kept in memory only. It is not placed in the URL, saved state, or
  stringified config output.

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
4 GB devices. Explicit clear controls and cryptographic tamper evidence remain
future work.

## USB localhost debug flow

1. Start the Hub on the Mac with a development token:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   export GOFFY_HUB_TOKEN='replace-with-a-long-random-development-token'
   .venv/bin/goffy-hub
   ```

2. On the Moto G, enable Developer options and USB debugging, then connect the
   device by USB and approve only the computer fingerprint you recognize.
3. Reverse the Hub port from the host to the phone:

   ```bash
   adb reverse tcp:8787 tcp:8787
   ```

4. Install and run the debug app from Android Studio or with the debug APK.
5. In the app, configure the Hub endpoint as `ws://127.0.0.1:8787/ws/v1`, then
   enter the legacy development bearer or the one-time returned paired bearer.
6. Submit `Show my Mac status` or `Check my Mac status`.

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
No camera permission dialog, camera privacy indicator, or image preview should
appear. Record failures when another camera app is active. Physical Moto G
verification remains open.

For the audit trail, complete one restart pass on a real device:

1. Produce at least one terminal PHONE record and, if a Hub is configured, one terminal MAC record.
2. Confirm the badge shows `AUDIT / READY / 50 MAX`.
3. Force-stop the app or reboot the phone, relaunch GOFFY, and confirm the newest terminal cards reappear as redacted history entries with target/tool/permission/phase and the audit timestamp.
4. Confirm restored cards are display-only: no structured result body, no pending approval controls, no active task, and no way to resume or replay authority from history.
5. Start a new approval-gated task, kill the app before it reaches a terminal phase, relaunch, and confirm there is no synthetic success row and no resumed approval.
6. If the badge reports `AUDIT / DEGRADED ...`, treat the stored history as partial and confirm GOFFY still does not alter the already shown execution verdict or schedule background retry work.
