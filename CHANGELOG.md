# Changelog

Changes in each version of Winlight, newest first. Version numbers follow the scheme in [docs/development.md](docs/development.md#versions-and-releases). Earlier, more detailed reports are kept in [docs/history/](docs/history/).

## 0.7.5 Beta 1 (unreleased)

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
