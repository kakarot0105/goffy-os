# Phone Tools

Android capability implementations expose narrow, typed local tools without a
generic Android-command interface.

The first tool is `phone.battery.status`. It reads `BatteryManager` once on user
request, requires no Android permission, validates the percentage, and emits a
separate verification event. The read runs off the UI dispatcher with a bounded
timeout. It does not register a receiver, poll, or run in the background.
