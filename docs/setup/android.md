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

## Real-device smoke test

1. On the Moto G, enable Developer options and USB debugging.
2. Connect by USB and approve only the computer fingerprint you recognize.
3. Select the physical device in Android Studio and run the debug app.
4. Confirm the launcher icon is legible in standard, round, and themed modes
   supported by the device.
5. Verify the GOFFY title, static orb, command field, mic/camera placeholders,
   disconnected Mac indicator, MAC target indicator, and empty timeline.
6. Rotate the phone, background/restore the app, and confirm no crash or visible
   input lag.
7. Use Android Studio Profiler to record cold-start time and idle memory for the
   device; add measured values to a future performance report.
8. Confirm the app does not appear in cloud-backup or device-transfer data.

No microphone or camera permission should be requested in Milestone 0.
