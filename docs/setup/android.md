# Android Setup

## Required tools

- Android Studio compatible with Android Gradle Plugin 9.2
- JDK 17
- Android SDK Platform 36 and Build Tools 36.0.0

Open the `android/` directory in Android Studio and allow Gradle sync to finish.
The app supports API 26 and newer and starts in GOFFY LITE mode.

From the repository root, run the pinned Gradle wrapper:

```bash
./android/gradlew -p android :app:lintDebug :app:testDebugUnitTest :app:assembleDebug --no-daemon
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
- Any extra instruction, unrelated command, or appended authority is rejected on
  the phone before a Hub connection opens.
- Android treats `ToolResult` as data only. The task becomes successful only
  after a matching `VerificationResult`.
- Battery status reads `BatteryManager` once per command, validates `0..100`,
  requests no permission, and performs no polling or background work.
- Device info reads static `Build` display fields once, requests no permission,
  and excludes identifiers such as serial, IMEI, Android ID, MAC, and fingerprint.
- Automatic reconnect is bounded to connection failures before the invocation is
  sent: at most 2 retries and 3 total attempts. After send, the client does not
  replay the request.
- Cancel only stops the local job and socket. Hub-side completion is not
  guaranteed.
- The bearer token is entered at runtime, sent only in the `Authorization`
  header, and kept in memory only. It is not placed in the URL, saved state, or
  stringified config output.

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
   enter the same bearer token.
6. Submit `Show my Mac status` or `Check my Mac status`.

Debug cleartext is allowed only for `localhost` and `127.0.0.1` through the
debug network security config. Release builds should use `wss://.../ws/v1`.
LAN use is still unsupported until trusted TLS and pairing exist.

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
