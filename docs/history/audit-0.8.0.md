# Audit report: 0.8.0 Beta 1

> **Archived.** This report records the audit of the code for 0.8.0 Beta 1 (November 2026), as it was at the time. Current behavior is described in [windows-notes.md](../windows-notes.md), and changes in the [changelog](../../CHANGELOG.md).

Every module was read against the design rules in [windows-notes.md](../windows-notes.md) and [development.md](../development.md), riskiest first: the native Windows code, the backends and their time limits, the monitor queue, night light, the app's wiring and quitting, the command pipe, files and settings, privacy, the system parts, and the windows. Each bug found was first shown by a test that failed, then fixed; the most important also have a case in `tests/test_mutations.py`, which breaks the fix again in a copy of the source and checks the test notices. The hardware checks passed on the test laptop afterwards.

## Bugs fixed

| Where | What went wrong | Who would see it |
|---|---|---|
| `hardware/win32.read_edid` | A monitor's EDID was read once per run. Windows keeps a monitor's record per port and updates it, so two identical monitors swapped between ports, or one replaced, kept each other's identity until a restart, with each other's brightness and names. | Anyone with two of the same monitor |
| `hardware/winsystem` | Power notifications were merged as repeats by their message, parameters and time. Sent messages share one time and a notification's parameter is a buffer's address, so a second notification through the same buffer was dropped (shown on the real message path; not seen from Windows itself). | Laptops: the panel's level after plugging in or unplugging |
| `brightness/monitors` | After a detection that didn't finish in time, the next one waited for every stuck call, not that detection. One display stuck for good stopped detection for the session. | A monitor that hangs, at the same time as a slow detection |
| `app._shutdown` | Quitting was one sequence; a failing step skipped the rest, the colors' restore among them. | Anyone, if a step ever failed |
| `app._reveal` | Explorer was started by its bare name, which Windows looks for in the app's and the current folder first. A rule now requires full paths. | Hardening |
| `core/shortcuts`, `cli/commands` | `isdigit()` is true for "²", which `int()` rejects: in a cycle shortcut's levels (AltGr+2 on German keyboards) it made the settings file unreadable at the next start, so every setting went back to its default. | German keyboards, and similar |
| `files.write_atomic` | Files weren't flushed before replacing the old ones: after a power cut, a settings file could be empty. | Power cuts |
| `brightness/keys` | The laptop-key follower's 2-second check started only if the panel was already found when it was turned on, which at start it never is. | Laptops that don't send Windows' brightness notification |
| `hardware/safe_mode` | The crash marker wasn't flushed, so a crash taking Windows down lost it, and the display was talked to again. Its exception to the atomic-write rule said a torn marker was "the safe outcome"; it is the unsafe one. | A monitor or driver that crashes Windows |

## Tests added

- A regression test for each bug above, and four new cases in `tests/test_mutations.py` (17 in all).
- `tests/test_settings_properties.py`: settings files with anything in any field. The earlier random test checked only that loading returns, which it always does (an unforeseen value sends it to default settings). This one checks that one bad value costs one setting. Random text almost never produces "²"; the strategies weight such characters in, and test each part of the file on its own, after a first version missed the bug it was written for.
- A rule in `tests/test_architecture.py`: every program is started by its full path.

## Noted, not changed

- **Clone mode and stuck calls.** In a clone group where only one monitor has a stuck call, the group's monitors are probed again, since Windows doesn't say which handle belongs to which target. A second stuck thread is possible in that case.
- **A detection that raises** would leave the brightness backend with no displays until the next one. The Windows calls it uses return empty results instead of raising, so this isn't reachable now.
- **The command line trusts the app's reply** to be an object. The reply comes from Winlight itself; validating it was ruled out in 0.7.5 as not needed.
- **Night light's gamma calls on the UI thread** have no time limit; since 0.7.5 a watch logs any that doesn't return. Moving them off the UI thread waits for evidence that it happens.

## Checked, no findings

The gamma backend (reviewed in 0.7.5), the brightness backend's detection and handle ownership, the call runner, night light's controller, remembered brightness, the brightness schedule, idle dimming, plugging in and unplugging, pausing, the display watcher, autostart, shortcut registration, the command pipe's access checks, the update check, privacy scrubbing, Report a Problem, the settings file's saving and migration, the command-line client, the entry point, and the panel's placement. The pure logic in `core/` was checked against its seeded soak and property tests, and the windows against `tests/test_frontend_audit.py` and their own tests.
