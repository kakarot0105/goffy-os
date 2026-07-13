# ADR 0005: Allowlisted system Clock timers

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY needs timers that survive its own process without a continuously running
countdown, foreground service, or local exact-alarm implementation. Android exposes
a documented Clock intent that starts a timer and delegates ringing, dismissal,
Doze behavior, and process independence to the device's Clock app.

## Decision

- Route only anchored numeric seconds, minutes, or hours commands to
  `PHONE / phone.timer.create / CONFIRM`.
- Accept 1 through 86,400 seconds, matching Android's `EXTRA_LENGTH` contract.
  Reject compound durations, overflow, appended instructions, and unsupported text.
- Reuse the exact-task, exact-tool, exact-arguments, expiring, one-time approval grant.
- Declare the normal `com.android.alarm.permission.SET_ALARM` permission and one
  `ACTION_SET_TIMER` package-visibility query. Do not request exact-alarm,
  notification, foreground-service, boot, or broad package-query capabilities.
- Allow only known AOSP and Google system Clock packages. Also require the resolved
  activity to be enabled, exported, and installed as a system or updated-system app;
  neither the system flag nor package name is treated as sufficient by itself.
- Reject Android's chooser and all non-allowlisted handlers, then pin the dispatch
  to the resolved explicit component.
- Dispatch only `ACTION_SET_TIMER`, the exact approved duration, and
  `EXTRA_SKIP_UI=true` on the main dispatcher. Send no unapproved message data.
- Return the exact requested duration, Clock package, Clock activity,
  system-install status, requested Clock-UI behavior, and system action as typed
  dispatch output. End the task `UNVERIFIED` because private Clock timer state is
  not readable by GOFFY.
- Run no countdown loop or polling. Android Clock owns timer lifecycle and alerts.

## Consequences

The timer remains active independently of GOFFY without continuous CPU work and
without special alarm access. The strict allowlist intentionally rejects third-party
Clock apps and unrecognized OEM packages for now. An unsupported Moto Clock package
fails visibly and emits no dispatch result until reviewed and allowlisted. Even a
successful dispatch remains visibly `UNVERIFIED` until a readable postcondition exists.

Robolectric covers the API 26 and API 33 framework branches and exact launched
intent. The target Moto Clock still requires physical-device testing. Future direct
timer state, cancellation, and listing should use a typed integration rather than
inferring another app's private state.

## References

- [Common timer intent](https://developer.android.com/guide/components/intents-common#Clock)
- [`AlarmClock.ACTION_SET_TIMER`](https://developer.android.com/reference/android/provider/AlarmClock#ACTION_SET_TIMER)
- [Package visibility declarations](https://developer.android.com/training/package-visibility/declaring)
- [`ApplicationInfo.FLAG_SYSTEM` caveat](https://developer.android.com/reference/android/content/pm/ApplicationInfo#FLAG_SYSTEM)
- [Alarm scheduling guidance](https://developer.android.com/develop/background-work/services/alarms)
