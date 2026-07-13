# Android Setup

## Required tools

- Android Studio compatible with Android Gradle Plugin 9.2
- JDK 17
- Android SDK Platform 36 and Build Tools 36.0.0

Open the `android/` directory in Android Studio and allow Gradle sync to finish.
The app supports API 26 and newer and starts in GOFFY LITE mode.

## Real-device smoke test

1. On the Moto G, enable Developer options and USB debugging.
2. Connect by USB and approve only the computer fingerprint you recognize.
3. Select the physical device in Android Studio and run the debug app.
4. Verify the GOFFY title, static orb, command field, mic/camera placeholders,
   disconnected Mac indicator, MAC target indicator, and empty timeline.
5. Rotate the phone, background/restore the app, and confirm no crash or visible
   input lag.
6. Use Android Studio Profiler to record cold-start time and idle memory for the
   device; add measured values to a future performance report.

No microphone or camera permission should be requested in Milestone 0.
