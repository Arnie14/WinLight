# Changelog

Changes in each version of Winlight, newest first. Version numbers follow the scheme in [docs/development.md](docs/development.md#versions-and-releases). Earlier, more detailed reports are kept in [docs/history/](docs/history/).

## 0.8.7 Beta 1 (2026-11-06)

### Fixed

- **Coming back to a screen Windows had turned off, it was still dimmed for a few seconds.** With "Dim displays when I'm away" on, Windows' own screen timeout turned the screen off over Winlight's dimming and brought it back at that level, and the laptop screen stayed dim until Winlight had detected the displays again. Winlight now reads when Windows dims or turns the screen off (from your power plan, without changing it) and brings the brightness back a few seconds before, so the screen wakes at its usual level. Where Windows would dim or turn the screen off before Winlight's own dimming time, Winlight doesn't dim it at all. While the PC is locked, the lock screen's own timeout (a minute after locking, by default) counts too.
- **The laptop screen's brightness comes back as soon as the screen is on**, however it went off (a lid, presence sensing), rather than after Winlight has detected the displays again, about 3 s later. It is set through Windows, so it needn't wait; external monitors over DDC/CI still do.

### Added

- **The welcome screen asks you to turn off Windows' automatic brightness** when it's on, as it does for Windows Night Light, with a button to Windows' display settings: it follows the room's light and moves the levels Winlight sets, the schedule's and your own. Winlight checks that the PC has a light sensor first; without one, the setting does nothing and Windows doesn't show it.
- **Settings > Brightness > When I'm away says what Windows' screen timeout does** beside Winlight's dimming, and **Screen timeout…** opens Windows' settings to change it or turn it off.

## 0.8.6 Beta 1 (2026-11-05)

### Changed

- **The log says what you did**, so a Report a Problem zip shows what was tried, not only what Winlight did: settings applied (which pages and settings, never their values), night light suspended, turned on or back to its schedule and from where (the tray menu, the panel, Settings, a shortcut, the command line), and brightness set by hand, once it settles (a drag is one line).

### Fixed

- The log said Winlight "last stopped unexpectedly" when one of its own earlier tints came back on a display while it was running (put back by Windows or the graphics driver; seen in a tester's report). It handled it rightly; the message now says what happened.

## 0.8.5 Beta 1 (2026-11-05)

### Added

- **The welcome screen lists your displays**, each with how Winlight controls it (DDC/CI, the laptop's brightness, Windows' brightness for SDR content), what to do for one that doesn't answer DDC/CI, and a note where HDR is on: Windows doesn't let night light tint a display in HDR.
- **It finds more tools that clash:** Iris, CareUEyes, ClickMonitorDDC, Dell Display Manager and LG OnScreen Control, besides f.lux, LightBulb, Twinkle Tray and Monitorian.
- **It says when Windows hides Winlight's tray icon** under ^ next to the clock, as Windows 11 does with every new tray icon, and opens the page to keep it on the taskbar. Winlight only reads where Windows keeps the icon; it never moves it.
- **It offers to start Winlight when you sign in** where it doesn't yet (the portable zip has no sign-in entry), with the same switch as Settings.
- **A form for reporting a problem on GitHub**, asking for what happened and when, the summary and the zip from Report a Problem, and which displays are involved. Report a Problem's **Open GitHub Issues** opens it with the version filled in, and nothing else.
- **The log says when Winlight quits, and why** (the tray menu, `--quit` from the installer or a script, Windows ending the session), and that it finished cleanly. A log that simply stopped looked the same as a crash or a power cut.

### Changed

- **Running the installer over an installed Winlight says it's an update**: which version is installed and which replaces it, keeping your settings, with an **Update** button. It always updated the same install in place; its pages just looked like a first install's.
- **An update replaces the app's files rather than adding to them.** Files an older version shipped and the new one doesn't were left behind (52 files, 17 MB, after a change of Python version on the test laptop), and an old system file there could have been loaded in place of Windows' own. Your settings are kept elsewhere and aren't touched.
- **A Winlight running from the portable zip is asked to quit** before the installed one starts at the end of Setup. The new one used to find it running, open its panel and exit, so the old version kept running until the next sign-in.
- **An update doesn't bring back a start-up entry you removed** with another tool (Autoruns, say), as f.lux's installer does at every update. Turning it off in Settings or Task Manager was always kept; ticking "Start Winlight when I sign in" in the installer, where it wasn't ticked before, still adds it.
- **One logo outside the tray.** Settings showed the day version of the logo while night light was off; it now always shows the dusk one, a little larger (64 px rather than 48), as the windows, the installer and the Start menu do. Only the tray icon follows night light.
- **Why Winlight? compares Iris, CareUEyes, ClickMonitorDDC, Dell Display and Peripheral Manager and LG OnScreen Control** too: what each adds, and when one may suit you better.
- **The welcome screen's cards scroll on a short screen**, the buttons staying in view: with several displays and tips it was taller than a 1366×768 laptop's screen.

- **The tray icon's menu is simpler and looks like Windows 11's.** It said "Suspend Night Light" twice: a check item (suspend until resumed) and a submenu (for an hour, until the evening, or until resumed), each doing something else; at noon it offered to suspend a night light that was off. There is now one Night Light item, named for what it does now: Suspend ▸ or Activate ▸, or Resume or Turn Off while one of those is on. **Open Winlight** comes first, in bold as Windows marks the default, and opens the panel, as clicking the icon does. Each item has an icon, drawn like Settings' own, and the menu follows Windows' light or dark taskbar. Suspending until resumed during the day, so that the evening wouldn't turn night light on, is no longer in the menu: turn night light off in Settings for that.
- **Report a Problem's box looks like Settings' questions**, with Show File, Open GitHub Issues and Close along its foot, rather than an old-style message box.
- **Settings > General > About ends with a note**: what Winlight is made for, and a request to anyone building on its code to keep the credit and the license, say what they changed, and not present their copy as Winlight.

## 0.8.0 Beta 1 (2026-11-04)

### Added

- **A welcome screen**, at the first start of a new install: today's night light and when it comes on, and what on your PC would clash with Winlight, each with what to do: Windows Night Light being on, f.lux, LightBulb, Twinkle Tray or Monitorian running, a monitor that doesn't answer DDC/CI. It links to switching from another app and opens Settings. It isn't shown after upgrading, waits for the next start if a fullscreen game or video is in front, and Settings > General shows it again.

### Changed

- **Night light is on screen at once when Winlight starts**, about 0.5 s after starting rather than 5 s on the test laptop. It used to wait for the app to be built (Windows' set-up of the first window takes up to a second) and then fade in over almost 4 seconds; at sign-in the screen had been bright for long enough already. Turning night light on, the schedule and resuming still fade. A display already showing a fullscreen game or video at start stays untinted from the beginning.
- **A new logo.** Winlight's icon is now a display with the sun setting in it, rather than the crescent moon most night light apps use. The tray shows it at dusk while night light is on and with the sun high in a pale sky while it's off; the windows, installer, Start menu and taskbar show the dusk one. At 24 px and below the display fills the icon, without its stand, so it stays clear in the tray. The panel's Night Light card keeps its moon and sun.
- **Brightness today is a chart.** The Brightness page drew the schedule's day as a strip of greys, darker where it dims, which said little: 40% and 60% looked alike, and a grey gives no number. It is now a small chart of the level from midnight to midnight, in the accent colour, with the level now beside the line at now. Night light keeps its ribbon, where the colour is the information.
- **Settings' questions look like Windows 11's.** "Apply your changes before closing?" and "Put the default settings back?" were drawn as old-style message boxes; they now have a title, a line of explanation and the answers side by side along the foot, the main one in the accent colour. Enter chooses the main answer, Esc keeps editing.
- **Settings is tidier** (from a review of every page):
  - A switch's details show only while it is on: "Dim displays when I'm away", "Selected apps" and "Never pause late at night" no longer take room with greyed-out controls and an empty list. An app list is as tall as its apps (up to five before it scrolls), and says "No apps added yet" when empty.
  - "No automatic DDC/CI writes in HDR" appears only for displays it applies to: controlled over DDC/CI, and able to show HDR (Windows says which). Where it is already on, it stays, so it can be turned off.
  - Time fields go round the clock: up from 23:00 is 00:00, for a bedtime after midnight.
  - A brightness schedule time by the sun says which way: "30 min after" or "15 min before" sunrise or sunset, rather than "30 min" or "-15 min". Typing a number, with a minus sign or "before", still works. Rows by the clock and by the sun line up.
  - Kelvin is written one way everywhere: "3800 K" in the panel and the tray tooltip too.
  - The note about Fn keys sits under the shortcuts it is about, and the welcome screen's "How to switch from another app" looks like the link it is.
- **Buttons no longer keep a ring after a click** (Apply, Reset and the welcome screen's), as switches stopped doing in 0.7.5: the ring shows when the keyboard moves to them.
- **Fades last as long as they should.** A 2-second change of temperature took nearly 4 seconds when the computer was busy, since it moved a fixed step at each timer tick; it follows the clock now.

### Fixed

- Swapping two identical monitors between ports, or replacing one with another of the same model, while Winlight ran: each kept the other's identity until Winlight restarted, so they took each other's remembered brightness and names. Windows keeps a monitor's record per port and updates it; Winlight now reads it afresh instead of once per run.
- Two of Windows' power notifications in a row could be taken for one repeated message, and the second dropped: for example the built-in display's new level straight after the charger is plugged in or unplugged, which "Keep brightness when plugging in or unplugging" relies on. Shown with Windows' own message path on the test laptop; whether Windows does this by itself hasn't been seen.
- After a detection that didn't finish in time, Winlight waited for every stuck call to return before detecting again, not only for that detection. With one display's call stuck for good, no detection ran again, and every display stayed out of reach until Winlight was restarted.
- Quitting was one sequence of steps: if one had failed, the steps after it were skipped, putting the colors back among them, and the screen stayed tinted after quitting until the next start. Each step now runs on its own.
- Report a Problem's Show File started Explorer by its bare name, which Windows looks for in the app's and the current folder first; it is now started from the Windows folder, as reg.exe is from System32. A test checks that every program is started by its full path.
- A "Cycle brightness through" shortcut whose levels held a character that looks like a digit but isn't one ("²", which AltGr+2 types on a German keyboard) raised an error in Settings, and once saved made the settings file unreadable at the next start, so Winlight started with default settings. Such characters are now left out of the levels. `winlight-cli --display ²` now says no display matches, rather than failing.
- Settings and state files are now flushed to the disk before they replace the old ones. After a power cut, a file could otherwise be left empty, and an empty settings file meant default settings at the next start. It costs about 3 ms per save on the test laptop.
- With "Follow the laptop's brightness keys" on, the check of the built-in display every 2 seconds never started after a normal start: it was turned on before the first detection had found the display. Only Windows' own notification was left, which some laptops don't send. It now starts once the display is found.
- After waking, a monitor that came back a few seconds late could go unseen for minutes. Once every display that answered before sleep had answered again, Winlight stopped checking, and also dropped the checks the displays coming on had asked for. If none had answered before sleep (one had just stopped), it stopped after two checks. Now it keeps the other checks, and checks for the full two minutes when there was nothing to wait for. Found in a tester's log.
- Waking was sometimes not noticed as a wake, when Windows synced the clock as it woke (which it often does) before Winlight next looked: the jump in time was put down to the clock change. Turning the displays on still worked, but the longer checks after waking didn't run, and a 6-hour sleep was logged as "going to sleep … but it is still running". Winlight now also measures time with a clock that counts sleep and that changing the clock doesn't move. Found in a tester's log.
- In the log and Report a Problem's "Last wake from sleep", checks left over when the PC slept again joined the previous wake's report ("After waking +29100 s", "detection took 1533.8 s"). The report now ends there.
- The panel said how a display's brightness is changed only for HDR displays and displays dimmed through their colors; monitors over DDC/CI and laptop panels, most displays, said nothing. Every display that can be changed now says how under its name ("DDC/CI", "Laptop brightness", "HDR · SDR content brightness", "Software dimming"), with more in its tooltip.
- Changing the theme in Settings left the quieter text (the tagline under Winlight's name, page subtitles, every setting's description) in the old theme's grey until a restart: dark grey on the dark background, nearly invisible. It follows the theme at once now, and so do the display icons in Settings > Displays.
- `winlight-cli` could wait 10 seconds and then say "Winlight didn't answer in time" although the answer had arrived: an answer that came in while the request was still being sent was left unread, as the command line only waited for more. It happened when the PC was busy; found by the tests on GitHub's runners and traced on the test laptop under load.
- A display whose call returned at the very moment Winlight gave up waiting for it (after 5 seconds) was left "Not responding" until Winlight restarted, and every detection skipped it. Found by running the tests in parallel.
- "Accepted 100% but reports 54%; it may ignore DDC/CI changes" was logged once per run. Winlight runs for weeks, so later changes the monitor ignored didn't show. It is now logged again after an hour.
- Crash safe mode's marker ("talking to this display now") wasn't flushed to the disk, so a crash that took Windows down with it lost the marker, and the display behind it was talked to again at the next start. It is written like every other file now.

### For developers

- The audit of the code for 0.8.0 is recorded in [docs/history/audit-0.8.0.md](docs/history/audit-0.8.0.md).
- `tests/test_settings_properties.py`: settings files with anything in any field must cost at most the setting concerned, never all of them.
- Groundwork for the Microsoft Store package, with no change to these builds: `system/packaging_info.py` tells whether Winlight runs from a package, and `visible_path()` gives the path Explorer and other programs see there (Windows redirects a package's app data). Report a Problem's Show File, Open log folder and the printed paths use it, and a test rule makes every function that hands a path to another program use it.
- A new test rule: every program is started by its full path.
- A panel test could fail after Settings' close question had run just before it, in the same process: the closed window's activation was still queued, and closed the panel's popup as it opened. Running in parallel put the two together; the test now lets queued events run first, and checks the popup is open.
- **The suite runs in about 2 minutes instead of 19 on the test laptop**, with every test kept. The collections after each test looked through every object in the process (166 ms each, twice per test, about half the run); everything that exists once the tests are collected is now frozen first, which alone took it to 8 minutes. The tests now also run on every core (pytest-xdist; `pytest -n auto --dist loadgroup`, as CI does), with the tests that use real hotkeys and key presses kept on one worker. A `slow` marker leaves the slow tier out while working (`-m "not slow"`). See [docs/development.md](docs/development.md#tests-and-lint).

## 0.7.5 Beta 1 (2026-10-30)

### Added

- **Pick apps by name.** Adding an app to "Pause for these apps" or "Never dim while these apps are in front" now offers your installed apps, from the Start menu, with a search box; apps running now are listed too. Browsing for a program file is still there, and starts in Program Files.
- **Brightness has a day of its own** on the Brightness page, as night light has: a strip from midnight to midnight, darker where the schedule dims, with a line at now. It follows the schedule as you edit it, before you apply it.
- **Settings > Displays says when a display is dimmed in software**: the picture is darkened, not the backlight, so it saves no power and blacks turn grey. Displays showing the same picture (clone mode) say they share one night light and one software dimming.

### Changed

- **Closing Settings with unsaved changes asks** whether to apply them or discard them. Before, they stayed in the window, unapplied, and were still there when you opened it again. Quitting Winlight or signing out never waits for an answer: unsaved changes are dropped.
- The **Pause night light** options say more plainly what each one does, and that each works on its own. "Video, calls and color apps" is now "Video, calls and color work".
- **Warmer night light** is listed among Winlight's features: it shows Windows' limit on how warm apps can make the screen, unlocks it, and locks it again.
- **Screen readers name every control.** Settings controls are named after their row ("Schedule", "Night"), each display's brightness slider after its display ("DELL brightness"), and the panel's icon buttons after what they do. Before, Narrator read many of them as just "combo box" or "slider".

### Fixed

- The panel's **Activate** button drew its arrow over its text. It's a split button now, like Suspend: click it for night light until you turn it off, or use its arrow for a set time.
- **Switches no longer keep a white ring after a click.** As in Windows 11, the ring shows only when the keyboard moves to them.
- If reg.exe, run to unlock or lock Windows' color limit, didn't finish in time, Winlight said it had failed but left it running, so it could still change the setting afterwards. It is now ended.
- A color profile whose calibration has an impossible gamma (infinite, or in the thousands) was read as a ramp black everywhere but at full white, and kept as the display's calibration: the screen went black under night light. Such a calibration is now refused as unreadable.
- When Windows failed for a moment to describe the displays, an HDR display looked as if HDR had been turned off, and each display lost its identity until the next check. What was known about each display is now kept until Windows answers again.
- At startup, Winlight checks each Windows structure it uses field by field, not only its size, and turns off only the feature concerned if one doesn't match.
- After a crash during software dimming between 20% and 39%, with the crash journal lost too, the dimmed ramp was taken for the display's calibration and dimmed again at the next start. Winlight now recognises its own dimming by its shape and puts the display's own ramp back (checked on the test laptop).
- A calibration whose curve dips a little near black (measurement noise in some profiles) wasn't kept under night light. A dip up to half a percent is accepted now; Windows takes such ramps as they are (checked on the test laptop).
- A gamma ramp call that the display driver doesn't return from within 5 seconds is now logged while it runs, and again when it returns, so a report shows it if a driver ever holds Winlight up.

### For developers

- Tests run on Windows for every push and pull request (`.github/workflows/tests.yml`), not only for releases and `main`.
- `tests/fake_windows.py`: a fake of every Windows display call the backends make, scriptable per call (return, raise, or stop at a gate until the test opens it), with a fake clock. `tests/test_concurrency.py` (`pytest -m concurrency`) stages races one interleaving at a time with it: several owners of one gamma ramp, a driver that doesn't return, another program changing the ramp between Winlight's change and its read-back, back-off on the fake clock with the real constants, displays unplugged mid-change. A rule keeps sleeps out of these tests; tests elsewhere that slept and hoped a thread had got somewhere now wait for events.
- Property tests with hypothesis (a new dev dependency, run derandomized): gamma ramps, the calibration heuristics, ICC and vcgt parsing over generated and damaged files, Windows calibration numbers of any kind, the DDC/CI retry loop over any sequence of answers, and the SDR brightness packet over any value.
- `tests/test_fault_injection.py`: any journal contents, a full disk, a truncated journal, and Windows' display query failing. `tests/test_ddc_retries.py`: DDC/CI retries end to end, through the real retry loop, backend and queue, and how failures add up in the manager.
- `tests/test_mutations.py`: each of 13 safeguards is broken on purpose in a copy of the source, and its tests must fail. Breaking them by hand first found a guard no test noticed (one display's unexpected error stopping the others), now tested.
- `tests/test_frontend_audit.py` asks Qt's accessibility layer what a screen reader says for every control. Field offsets of every native structure are checked, and a rule keeps the DDC/CI capabilities string from being asked for.
- The gamma backend takes its clock as a parameter, as `MonitorService` does.

## 0.7.0 Beta 1 (2026-10-30)

### Added

- **Cycle brightness shortcuts**: one shortcut steps through levels you list, such as 100, 50 and 1, then round again (Twinkle Tray #898). Each display goes to the level after its own; a display at another level starts from the first.
- **A shortcut to detect displays again**, as the panel's ⟳ button and `winlight-cli --refresh` do (Twinkle Tray #585).
- **Add the usual** on the Shortcuts page: Ctrl+Alt+Up and Ctrl+Alt+Down for brighter and dimmer, in one click.
- **A Command line section** on the Shortcuts page: whether `winlight-cli` is ready to type (on PATH), its full path to copy if not, a few examples to copy, and a link to the full command reference.
- **What night light is doing now**, under the day on the Night Light page ("Now: Night · 4500K"), with its next changes.

### Changed

- **Unsaved changes are marked**: a dot on each page that has changes not yet applied, and "Unsaved changes" next to Reset and Apply.
- **Restore defaults** moved to the foot of the navigation pane, beside the version: it concerns every page, so it sits away from Apply. It asks first, naming the pages it changes; nothing is saved until Apply.
- **Windows' color limit is always shown** in Settings > Night Light, with its state: locked or unlocked, whether that's in effect yet (Windows applies a change after signing out), and the displays it holds back. The button unlocks it, or **locks it again**. Before, the option disappeared once the limit was unlocked, leaving no sign of it and no way back. Uninstalling offers to put the limit back, No by default, since f.lux and LightBulb rely on the same setting.

### Fixed

- The Shortcuts page's description began "Work in any app"; it reads "Shortcuts work in any app". "Never open over fullscreen apps" says which windows it means, and that pausing night light for fullscreen apps is a separate setting.

## 0.6.0 Beta 1 (2026-10-29)

### Added

- **Check for updates** (Settings > General > Updates), off unless you turn it on. Once a day, and when you click Check now, Winlight asks GitHub whether a newer version is out and, if so, says so once in a notification; clicking it opens the release page. It downloads and installs nothing. This is the only time Winlight connects to the internet: leave it off if you prefer that. While Winlight is in beta, turning it on is recommended.

### Changed

- **Switching night light back returns to the schedule.** The night light shortcut and `--night-light toggle` switch night light on or off until switched back; switching back now follows the schedule again. Before, pressing twice in the day left night light "suspended until manually resumed", so the evening never came.
- **Shortcuts for every display leave alone a display set to "No automatic DDC/CI writes in HDR"** while it's in HDR. A shortcut for that display still changes it.
- **"Dimmer" never raises a display, and "Brighter" never lowers one**, also from below a display's lowest level.
- **Alt+Space can't be a shortcut** (it opens every window's menu, and PowerToys Run). **Ctrl+Alt with a letter, digit or punctuation key works, with a warning**: on keyboards with AltGr, Ctrl+Alt+E is AltGr+E, which types € on German, French and Polish layouts, and wouldn't type any more.
- A shortcut Windows refuses says "Windows or another app has these keys" (Win+L is Windows' own), and Report a Problem lists every shortcut and how it stands.
- Settings > Displays explains under its list that "No automatic DDC/CI writes in HDR" is for troubleshooting, and which features a display loses with it.
- **The uninstaller asks whether to delete your settings** too, and does by default: an uninstall removes everything.

### Fixed

- A settings file with a number too large to read (such as `1e400`) stopped Winlight from starting. Such a value now falls back to its default, and any other unforeseen problem reading settings starts Winlight with default settings, keeping the file aside.
- A Windows message for a shortcut id outside an app's range raised an error inside the message handler; it's ignored.
- Signing out stopped the shortcuts, but a recording field losing focus afterwards registered them again.
- **Night light jumped when the morning began before the evening's change was over** (a long transition with a short night: night at 22:00 with 10 hours of change, day at 06:00). The evening's change now speeds up to finish as the morning's begins, so night light turns round smoothly.
- **Two writes of the same file at once could leave half a file** (the gamma journal, written by a call given up as stuck and by the next one): each write now has a temporary file of its own.
- After signing out started, the display watcher still passed on sleep, wake and display events, and the update check kept its daily timer; both stop now.
- Saving settings that didn't change night light (Apply on another page) wrote the gamma ramps again.

### For developers

- `tests/test_shortcut_safeguards.py`: the key rules' edge cases, settings that can't be read, the service's lifecycle, the toggle from every starting state (shortcut and command line alike), real key presses, another process refused the keys, quitting leaving none registered, 10,000 random presses with failures, and garbage collection and threads.
- Shortcuts past the 32 kept are logged.
- **Tests that guard the design.** `tests/test_architecture.py` reads the source and fails on a broken rule, naming the line: Windows calls without declared types, shared `ctypes.windll`, signals emitted under a lock, threads that aren't named daemons, sleeping on the main thread, nested event loops, direct connections, timers without an owner, files written without `write_atomic`, child processes waited for without a timeout, `print` in the app, swallowed broad exceptions, unfrozen settings; each rule is also fed the mistake it's for. `tests/test_design.py` and `tests/test_concurrency_and_soak.py` try the design's promises: every setting surviving the Settings window and the file, thousands of random settings files, idempotency, schedules within bounds anywhere at any moment, the monitor queue and the gamma backend from many threads, starting and quitting repeatedly, Qt objects on the main thread and freed, random event orders for the display watcher, atomic writes against concurrent readers and writers, soaks of night light and the brightness schedule, and the suite passing in reverse order. `conftest.py` now fails any test that raises inside a Qt slot, makes Qt warn, leaves a thread running, or raises in a thread or a finalizer, and ends a hung run with every thread's stack; `tests/test_suite_guards.py` checks each guard.
- No lambda connected to a signal holds `self` any more (a test checks every module): the settings window, its widgets, the brightness schedule, the laptop-key follower and the power-source handling connect bound methods, which can't make the reference cycles behind 0.5.0's exit crash. The command-line pipe's per-request sockets are the one exception, and say why.
- Layers: the settings model moved to `core/settings.py` (`config.py` keeps reading and saving it, and its names); atomic writes and garbage collection moved to `nightlight/files.py` and `nightlight/gc_guard.py`, and crash safe mode to `hardware/safe_mode.py`. A test checks which layers each one may import.
- `SetCurrentProcessExplicitAppUserModelID` is called with declared types, as every other Windows call.
- The settings file's version is 3 (the update check).

## 0.5.0 Beta 1 (2026-10-26)

### Added

- **Keyboard shortcuts** (Settings > Shortcuts): brighter or dimmer by a step, a set brightness, night light on or off, suspend or resume, and opening the panel, for every display or one. Click a shortcut's field and press the keys to record them. Each shortcut says whether it works, or whether another app already has its keys. Holding a brightness shortcut keeps stepping, and each display steps from its own level. A shortcut whose keys another app has is tried again every 30 seconds, so it works once that app quits. The panel's shortcut closes the panel when pressed again.
- **A note at the bottom of the screen** shows the new levels or what changed after a shortcut, for two seconds. It never takes focus, and isn't shown over a game in exclusive fullscreen. It can be turned off on the Shortcuts page.

### Changed

- Settings opens at start (when "Start minimized" is off) once everything else has started, rather than part way through.
- **Settings survive going back a version.** Settings a newer version saved and an older one doesn't know, shortcuts among them, are kept when the older version saves, so updating again finds them. LightBulb's users lost their hotkeys this way.

### For developers

- Tests for recording and checking keys, registering shortcuts with Windows (taken keys, the same keys twice, pausing while recording), held keys, per-display steps, and a check in `tools/hardware_checks.py` that registers a shortcut, presses it on the real keyboard input, and checks that the note never takes focus.
- The editors' remove buttons no longer hold their row in a reference cycle, which crashed Python as it exited after the tests had passed (the first 0.5.0 build failed on it).
- Every hotkey report and commit in Twinkle Tray and LightBulb was gone through; the ones that apply are guarded by tests that cite them.

## 0.4.0 Beta 1 (2026-10-23)

### Added

- **A day ribbon**: the Night Light page opens with today from midnight to midnight, each moment painted in the white your screens show then, with a line at the time now. It follows the settings on the page before you apply them, and the 24-hour preview moves its line. The panel has a slim one under Night Light.
- **The panel's Night Light section** is a tile that takes on the screens' warmth now: neutral by day, amber at night.
- **The temperature sliders** show the temperatures they set: their track runs from neutral white to the warmest amber.
- Titles use Windows 11's display typeface (Segoe UI Variable Display).

- **Unlocking warmer colors**: where Windows holds night light back, Settings offers to unlock it, as f.lux and LightBulb do. It sets the `GdiIcmGammaRange` registry value after Windows' administrator prompt; declining the prompt changes nothing.
- **A 24-hour preview**: the next day of the settings in Settings, on screen in about 20 seconds, as in LightBulb.
- **Keep brightness when plugging in or unplugging** (Settings > Brightness): Windows' power plans set their own level for the built-in display then; Winlight puts yours back, without changing the power plans.
- **No automatic DDC/CI writes in HDR**, per display (Settings > Displays): for monitors that show a tint after DDC/CI brightness changes in HDR mode.

### Fixed

- **Night light was off after midnight in UTC+13 and UTC+14** (Tonga, Samoa, Kiribati, Tokelau) with a sunset-to-sunrise schedule, since 0.3.0 Beta 2: the evening before went missing from the schedule.
- **File Explorer kept a pause going**: leaving a paused video or listed app for File Explorer left that display without night light, because File Explorer runs as `explorer.exe`, like Windows' shell.
- **The settings window's navigation** kept an outline on the page entry used last after it was closed and opened again, while another page was shown. The outline now shows for keyboard focus only, as in Windows 11.

### For developers

- Tests for time zones ahead of their solar date, File Explorer, and choosing a display's color profile (per user, system-wide, none).

## 0.3.0 Beta 2 (2026-10-22)

### Added

- **Suspend until resumed**, as in KDE: the panel's Suspend button keeps night light off until it is clicked again, in the day too; its arrow has the timed choices. The tray menu has the same toggle, and the command line `--night-light suspend` and `resume`.
- **Never pause late at night**: a fourth pausing option. From night light starting to warm, being fully on, or a set time such as bedtime, until the morning transition, nothing pauses night light: no fullscreen app, listed app or automatic pause.
- **A note on screen while previewing**: holding a temperature slider shows "Night light preview" and the temperature in the middle of the screen, until the slider is let go.
- **Calibration status, Reload and Forget**: Settings > Displays shows each display's color calibration. Reload reads it again from the display's color profile and puts it on screen; Forget stops Winlight putting back a calibration you removed in Windows. On the command line: `--calibration status`, `reload` and `forget`. The first time a calibrated display is found, a notification explains keeping calibrations, once.

### Changed

- **High latitudes get their real sunset and sunrise.** In Reykjavik from May to July the sun sets but twilight never ends, and on some summer days in Stockholm and Helsinki dusk comes near midnight; the whole schedule fell back to 18:00 and 06:00 on those days. Night light now turns at solar midnight in a white night, and the brightness schedule's sunrise and sunset come from the same calculation.
- **A maximized window no longer counts as fullscreen**, also with the taskbar hidden automatically: Winlight measures the window's client area, without its title bar, and leaves out maximized windows that draw their own (VS Code, browsers).
- **While the displays are off**, the gamma checks and watching the app in front slow down rather than run as usual.
- The calibration status counts how often a calibration was put back today, and says "None detected" for a display without one.
- **Night light comes back more reliably after waking, unlocking and displays turning on**: the ramps are set again several times over 2 s even where Windows reports them unchanged, then checked for 12 s. Each ramp differs a little from the last (LightBulb's rotating offset), since some drivers ignore one they were sent before. Windows resetting the ramps meanwhile no longer counts as another program fighting over them.
- **More of Windows' own interface is told apart from fullscreen apps**: Start, search, Alt+Tab, Task View, Quick Settings, the lock screen and others (LightBulb's list, extended for Windows 11). Opening them over a paused video keeps the pause. Store apps are recognised by their own names for the app list.
- Settings opens on the first page, at its top, and each page opens at its top.

### Fixed

- **The settings window's first opening flickered**: about 40 small windows flashed over the screen while it was built, which also made it take about a second to open.
- Starting at sign-in compared program paths without case only on Windows; the test failed elsewhere.
- A gamma ramp change stuck in a display driver on the monitor thread could freeze the app at the next night light change. The app now waits at most 2 seconds, skips the change and says so once.

## 0.3.0 Beta 1 (2026-10-20)

### Changed

- **Data folder and log renamed.** Settings, state and logs move from `%LOCALAPPDATA%\night-light` to `%LOCALAPPDATA%\WinLight`, and the log from `night-light.log` to `WinLight.log`, its history included. The first start renames the folder, so nothing inside it changes; if an older copy still has it open, the old folder is used and the rename is tried again at the next start. Going back to 0.2.0 or earlier afterwards starts with default settings.
- **Report a Problem** saves its zip in `%LOCALAPPDATA%\WinLight\Reports` instead of on the Desktop, which OneDrive's folder backup often syncs to the cloud. Old zips on the Desktop are still deleted after a week.
- **Windows 11** is the supported system; Windows 10 hasn't been tested.
- The project's repository is now `github.com/Arnie14/WinLight`.
- Windows' file version is numeric (`0.3.0.2001` for 0.3.0 Beta 1), so it always increases from one beta to the next and on to the release.

### Added

- **Windows' limit on warm colors is shown.** Windows refuses gamma ramps far from neutral; when it holds a display warmer than asked, Settings shows the limit under the night temperature ("Built-in display: 3300 K (Windows limit)"). The sleep recommendation explains it, and asks each display for the warmest it accepts.
- **SHA-256 checksums.** Each release has a `SHA256SUMS.txt` with the checksum of every download, also listed on the release page, to check a download with `Get-FileHash`.
- **Third-party notices** (`THIRD_PARTY_NOTICES.txt`) ship with the app: Qt and PySide6 (LGPL-3.0), Python, the PyInstaller bootloader, astral, tzdata, platformdirs, WMI and pywin32, with their license texts. Settings > General > About opens them.

### Fixed

- **Calibrations to a warm white point were discarded.** A ramp with a channel below 90% was taken for a leftover tint and reset to neutral, so a calibration to D50, say, was lost until Windows loaded it again at the next sign-in. A ramp is now rejected only if it is also shaped like a tint (straight channels); Winlight's own tints are recognised by its crash journal first.
- **The command pipe** now checks that the program serving it runs as the same user before sending anything. Its access list already kept other users from connecting; the check covers another user's program taking the pipe's name first.

### For developers

- `nightlight/` is grouped into subpackages: `brightness/`, `color/`, `system/`, `support/` and `cli/`.
- Dependencies live in `pyproject.toml` only, with `dev` and `build` extras (`pip install -e ".[dev,build]"`).
- Ruff checks a wider rule set, configured in `pyproject.toml`, and CI runs it.
- New tests check every import, lint the documents, and pin the installer's AppId and the version scheme.
- CI reports each run's test counts in its summary; the documents no longer quote counts.
- `tools/hardware_checks.py` checks the backends against the real Windows APIs on any PC.
- The README is shorter; features and status, the comparison with other tools, the command line, development and the Windows notes each have their own page.

## 0.2.0 Beta (2026-10-19)

### Added

- **Pausing night light per display, three ways:** for any fullscreen app; for apps on a list (in front, fullscreen or not); and automatically for video playback, calls, exclusive-fullscreen games and well-known photo, video and design apps, as Windows reports them.
- **Sunrise and sunset transitions** follow twilight, or last a length you choose (none, or 5 to 120 minutes).
- **Sleep-friendly recommendation:** a full schedule from your bedtime and wake-up time, or just the warmth (2700 K).
- **Brightness presets** change gradually, with times and levels true to their names. A schedule saved from an older preset is shown as Custom.
- **The tray tooltip and panel** show the brightness schedule ("70% → 40% at 20:00").
- **Never dim while these apps are in front**, for dimming when idle.
- **Theme and accent color** choices.

### Changed

- **Starting at sign-in** is set up by the installer, on by default; the setting switches it on and off as Task Manager does. The app no longer rewrites its Run value at every start, which Microsoft Defender's behavior monitoring flagged in 0.1.0 Beta 5 (`Behavior:Win32/Persistence.A!ml`).
- **Dimming when idle** no longer stops for any window that fills the screen (a browser or an editor in fullscreen); only an app keeping the screen on, an exclusive-fullscreen game or a listed app hold it.
- **Report a Problem** deletes its zip after 7 days and clears its summary from the clipboard after 10 minutes. Its message is shorter.
- Settings text was rewritten throughout for clarity and consistency.

### Fixed

- The settings window was taller than some screens (960×760 at 150% scaling on 1080p), so restoring it from maximized looked like nothing happened. It now fits the screen.
- Windows showed a white frame before the settings window's first paint in dark mode. Windows now fade in after their first paint.
- With a location far from the PC's time zone, the morning twilight was paired with the next day's sunrise and "ended" before it began.
- After signing out began, a late display change could re-tint the screen, and the idle dimmer could dim it again.
- Input that turned the displays off was read as them being back on, so DDC/CI could reach monitors that were asleep.
- A display that kept changing (a loose cable) postponed re-detection indefinitely.
- Releasing the WMI connection collected garbage on the monitor thread, which can destroy Qt objects off the main thread; its COM cycles are now broken on that thread instead.
- Monitor handles leaked if opening them failed partway; the app list could stop early on one failing window.
- The command pipe failed on requests split across reads, and on answers to a command line that had already hung up.
- An unreadable settings file was overwritten with defaults; a copy is now kept as `settings.json.damaged`.

## 0.1.0 Beta 5 (2026-10-19)

The reliability and redesign release: one serialized monitor queue with time limits, stable display identity, an idempotent brightness scheduler with presets, the compatibility report, the gamma crash journal, and the redesigned settings window, merged with every beta 3 and 4 feature.

- **HDR:** a monitor that locks its brightness in HDR mode is noticed and moved to Windows' SDR content brightness.
- **Command line:** `--panel`, and displays chosen by part of their id.
- **Keep each display's color calibration** (optional).
- Per-display pausing names the display; a minimized window no longer keeps night light paused.
- **Notable fixes:**
  - A ramp Windows reset was sometimes adopted as the new base.
  - An app already in front at start didn't pause night light.
  - A WMI reading taken just after a write showed the old level.
  - The time zone name appeared in reports.
  - Several races between sleep, detection and stuck calls.
  - Another program's gamma ramps were fought over, flickering the screen.
  - Exceptions in Qt slots were lost.
  - A crash when garbage collection ran on a monitor thread.

## 0.1.0 Beta 4 (2026-10-17)

- Dimming when idle, the safe way for each kind of display: external displays in software, never over DDC/CI.

## 0.1.0 Beta 3 (2026-10-17)

- Pausing night light for apps and fullscreen.
- Night light back at once after unlocking.
- A brightness schedule.
- `winlight-cli`, with an optional PATH entry.
- Report a Problem.
- Crash safe mode for DDC/CI.
- Renaming and hiding displays.
- Personal details kept out of logs and diagnostics.
- Never opening windows over a fullscreen game.
- Following the laptop's brightness keys on external displays.
- Re-detection after waking, with timings in the log.
- Betas are published as full releases.

## 0.1.0 Beta 2 (2026-10-17)

- SDR content brightness for HDR displays, and software dimming for displays without brightness control.

## 0.1.0 Beta 1 (2026-10-17)

The first Windows build:

- night light with a schedule by custom times or a city's sunset and sunrise;
- brightness for laptop panels (WMI) and external monitors (DDC/CI);
- remembered brightness;
- starting at sign-in;
- the tray panel and settings;
- the installer and the portable zip.
