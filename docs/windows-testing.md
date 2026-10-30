# Windows test plan

A checklist for running Winlight from source on real Windows 11 hardware. The unit tests cover the Windows backends against a fake of the Windows APIs, and `tools/hardware_checks.py` covers them against the real APIs; this plan covers what needs real monitors and a person at the screen. Testers using the installer can follow the shorter [testing-installer.md](testing-installer.md). The background for many checks is in [windows-notes.md](windows-notes.md), and how far each feature has been tested is in [features.md](features.md).

Note the hardware for each run: Windows version, GPU and driver, each monitor's model, and how it's connected (HDMI, DisplayPort, USB-C, dock).

## 0. Setup

```powershell
git clone https://github.com/Arnie14/WinLight.git
cd WinLight
py -3 -m venv .venv          # Python 3.12 or newer, from python.org
.venv\Scripts\activate
pip install -e ".[dev]"      # includes wmi and pywin32 on Windows
```

Create `.venv` on the machine that uses it: a virtual environment copied from Linux (or the other way round) doesn't work.

Before testing night light:

- Turn off **Windows Night Light** (Settings > System > Display > Night light), f.lux, and AMD's "Custom Colors" or NVIDIA's color settings, if you use them. They are tested together with Winlight in §8.
- Turn on **DDC/CI** in each external monitor's on-screen menu. It is sometimes off by default.
- Quit any installed Winlight (`Winlight.exe --quit`): two copies, or one installed and one from source, would fight over the colors.

## 1. Automated checks

```powershell
pytest
ruff check .
python tools/hardware_checks.py
```

- [ ] `pytest`: everything passes, in 10 to 15 minutes. On Windows the only skip is the import of the Linux-only KDE backend. A failure in `test_win32.py` or `test_winsystem.py` means a binding is wrong; send its output. `pytest -m concurrency` runs only the race tests, in seconds.
- [ ] `ruff check .`: no findings.
- [ ] `hardware_checks.py`: no FAIL lines. It tests the built-in panel if there is one, otherwise the first display, and puts colors and brightness back at the end. Send its whole output, including the INFO and SKIP lines.

## 2. Probe and compatibility reports

```powershell
python main.py --probe
python main.py --report
```

`--probe` prints, and saves to the log folder as `probe.txt`, what each API says about every display. It changes nothing, except that each display is briefly tinted to find the warmest night light Windows allows, then restored. `--report` prints the compatibility report (also in Settings > Displays) and sends nothing to the displays.

- [ ] "Windows capabilities and ctypes layouts" says `layout problems: none` (sizes and field offsets).
- [ ] Each monitor appears under "Displays" with its real model name, connector, HDR state and an "EDID:" line. Two identical monitors have different identities if their EDID has a serial.
- [ ] Each external monitor with DDC/CI on reads a brightness under "DDC/CI monitors" ("VCP 0x10 brightness: N of M").
- [ ] A laptop panel appears under "Built-in panels (WMI)".
- [ ] "Warmest night light Windows accepts" shows a temperature: the limit described in [windows-notes.md](windows-notes.md#3-gamma-ramps-night-light-dimming-and-calibrations).
- [ ] The compatibility report lists each display once, with "Brightness:" matching how it really works, or "not controllable" with a reason and something to try.

**Send both reports back**, whatever the results.

## 3. Start, tray and panel

```powershell
python main.py --debug
```

The log is also written to `%LOCALAPPDATA%\WinLight\Logs\WinLight.log`; its path is printed at start. The first start of a version from 0.3.0 renames an existing `%LOCALAPPDATA%\night-light` folder to `WinLight` (the log says "Renamed the settings folder"), keeping its settings.

- [ ] A sun or moon icon appears in the tray, sharp at your scaling and readable on a light and a dark taskbar. Repeat the checks below with the icon in the overflow (^) area too.
- [ ] Hover over the icon: "Winlight", "Night Light: …" with the status, the brightness schedule's level while that schedule is on, and any display night light is paused on.
- [ ] Left-click: the panel opens just above the taskbar, its right edge in line with the icon (or in the corner by the clock), about 12 px from it.
- [ ] Click the icon again: the panel closes and doesn't reopen. Click on the desktop or another window: it closes. Press Esc: it closes.
- [ ] Right-click: Suspend or Activate, Settings…, Report a Problem… and Quit.
- [ ] With night light off, the panel's **Activate** button shows its text and its arrow apart: clicking it turns night light on until you turn it off; its arrow offers set times.
- [ ] Settings, from the tray menu and from the panel's ⚙, in dark mode: no white flash. Maximize the window, then restore it: it returns to its smaller size, inside the screen.
- [ ] Set the taskbar to auto-hide: the panel still opens next to it.
- [ ] Restart Explorer (Task Manager > Windows Explorer > Restart): the tray icon comes back.

## 4. Brightness

For each external display, note: brand and model, the connection (HDMI, DisplayPort, USB-C, Thunderbolt; direct, adapter, hub or dock), and the GPU it is plugged into.

Per external monitor:

- [ ] The panel lists it by model name, with its current brightness.
- [ ] Dragging the slider changes the monitor's brightness **while dragging**, and the UI never freezes. After a fast drag the monitor ends at the slider's final value.
- [ ] 0% and 100% match the monitor's own minimum and maximum.
- [ ] Change brightness with the monitor's buttons, then reopen the panel after 5 s or more: the slider shows the new value, and Winlight doesn't change it back.
- [ ] A monitor with DDC/CI off shows a **disabled** slider with "DDC/CI didn't answer"; after turning DDC/CI on, ⟳ brings it back.
- [ ] No slider ever moves without changing anything: whenever a display can't be changed now, its slider is disabled with a few words saying why.
- [ ] Turn the monitor off with its power button and on again: it works again within about 10 s.
- [ ] Sleep the PC with the monitor connected and wake it: the monitor isn't woken by Winlight on its own, and works again within about 30 s. **Note any monitor that stays black or needs unplugging.**
- [ ] Note any flicker while dragging, or a monitor that changes in visible steps.
- [ ] A slider saying "Not responding": note which display and what you were doing, and send the log. The other displays keep working.
- [ ] A slider saying "The last change failed", or a display marked failing: note how often, and send the log. Lines such as "transient DDC/CI error 0xC0262583, retrying" (with `--debug`) show messages garbled on the cable and sent again; many of them suggest trying another cable or port.

TVs and displays without DDC/CI:

- [ ] Listed with "Software dimming" under the name (Settings > Brightness > "Dim displays without brightness control", on by default). If it says "DDC/CI didn't answer" instead, send `probe.txt`.
- [ ] Its slider dims the picture smoothly down to 20%; note how dark 20% looks and any banding.
- [ ] With night light on, the TV is both dimmed and warm; turning night light off keeps it dimmed. Quitting Winlight restores full brightness; starting it again dims it again (with "Remember each display's brightness" on).
- [ ] Turning "Dim displays without brightness control" off restores full brightness at once and shows "not supported".
- [ ] A TV with a real brightness slider (working DDC/CI): note the brand and model.

HDR displays (Settings > Display > Use HDR):

- [ ] An HDR display without DDC/CI shows "HDR · SDR content brightness"; its slider and Windows' "SDR content brightness" slider agree after reopening the panel.
- [ ] An HDR monitor with DDC/CI starts on DDC/CI. Move its slider: if the brightness changes, it stays on DDC/CI; if not, within about 2 s the log says its brightness looks locked and the slider becomes "SDR content brightness" at the level you chose. Note the model and which happened.
- [ ] Turn HDR off and on with Winlight running: the slider switches between the two within a few seconds. Night light skips the display while HDR is on.

Laptop panel:

- [ ] The panel ("Built-in display" unless its EDID names it) has a working slider that stops at 1%, never black.
- [ ] Windows' own brightness slider and Winlight's agree after reopening the panel.
- [ ] Unplug and replug the charger, or switch power mode: if the brightness jumps back, note it.

Docks, adapters and ports:

- [ ] A monitor on a DisplayLink/USB dock is listed as not supported, with the DisplayLink reason.
- [ ] A monitor through a USB-C or Thunderbolt dock, a converter, a KVM switch or MST daisy-chaining: does DDC/CI work?
- [ ] The same monitor on HDMI and on DisplayPort: its remembered brightness follows it between ports.

Options (Settings > Brightness):

- [ ] **Remember each display's brightness** (on by default): set distinctive levels, quit and start again: they come back within a few seconds ("Restoring … brightness" in the log). Unplug a monitor, change it with its buttons, plug it back in: it returns to Winlight's level.
- [ ] `%LOCALAPPDATA%\WinLight\brightness.json` lists each display by a code such as `DEL41A2`, followed by its serial when the EDID has one (`DEL41A2:7XKJ9F3`). Two identical monitors have different codes, and keep them when swapped between ports.
- [ ] **Change all displays together**: one slider moves every display, smoothly.
- [ ] Laptop with an external monitor: **Follow the laptop's brightness keys**, then press the keys: the external monitor follows within about 2 s. The log says whether Windows reported it or the check found it; note which. The panel's own laptop slider doesn't move the others.

## 5. Night light

Settings > Night Light, Schedule **Always on**:

- [ ] Applying fades every display warm over about 2 s; dragging a temperature previews it live.
- [ ] Drag the night temperature fully warm. If Windows refuses that, each display stops at the limit `--probe` found, the log has one warning about `GdiIcmGammaRange`, and the Night row names each limited display ("3300 K (Windows limit)"). Back within the limit, the note disappears.
- [ ] Optional: **Unlock…** under the Night row, and accept the administrator prompt: "Windows' color limit" says unlocked, in effect after signing out, and `GdiIcmGammaRange` (DWORD `256` under `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ICM`) is set. Sign out and in: warmer temperatures now work. **Lock again…** removes the value the same way. Declining the prompt changes nothing.
- [ ] Quit from the tray menu: the displays return to normal colors. A calibrated display returns to its calibrated look, not a flat one.
- [ ] At 4500 K or warmer, end Winlight from Task Manager, then start it again: the log says the display "still had the tint Winlight left when it last stopped unexpectedly", and quitting returns the screen to normal.
- [ ] In a terminal, Ctrl+C or closing the window: "quitting cleanly", colors back to normal.

Schedule:

- [ ] **Custom times** a few minutes ahead: the transition starts and ends on time; the tray icon and status follow.
- [ ] **Sunset to sunrise**: type part of your city in Location ("lond"), pick it from the list; after Apply the times shown match a sunrise/sunset table. **Detect** picks the city of your time zone. **Custom location** shows Latitude and Longitude, filled from the last city.
- [ ] **Transition**: twilight, none, or 5 to 120 minutes; the times listed change to match.
- [ ] Suspend for 1 hour and Resume, from the tray menu and the panel.

Sleep recommendation (Settings > Night Light > Sleep):

- [ ] **Use sleep schedule** with a bedtime and wake-up time: custom times starting 3 hours before bedtime, a 60-minute transition, 2700 K (or your warmer choice); nothing changes until Apply.
- [ ] **Use warmth only**: only the night temperature changes.

## 6. Pausing night light and dimming when idle

Pausing (Settings > Night Light > Pause night light):

- [ ] **Fullscreen apps**: a fullscreen video (browser F11 or a player) and a game, borderless and exclusive, each fade their display to normal colors within about half a second; the other displays stay warm. Leaving fullscreen fades it back. Note any game that isn't detected.
- [ ] **Selected apps**: add an app three ways from "Add an app": "Choose from installed apps…" (search for one, such as VLC), a running app, and "Browse for a program file…". Switching to it pauses its display, fullscreen or not; switching away, minimizing or closing it resumes.
- [ ] **Video, calls and color work**: a video playing in a window, a video call, an exclusive-fullscreen game, and Photoshop or Lightroom each pause the display in front. Note anything it misses or pauses wrongly.
- [ ] The panel and the tray tooltip say "Paused on <display> for …" meanwhile.

Dimming when idle (Settings > Brightness > When I'm away, e.g. 1 minute to 20%):

- [ ] Leave the PC alone: every display fades to 20% (darker displays stay as they are). Move the mouse: they come back within about a second.
- [ ] A video playing (windowed or fullscreen), a call, an exclusive-fullscreen game or a PowerPoint slideshow: nothing dims. A web page in fullscreen (F11) with nothing playing: the displays dim. An app under **Never dim while these apps are in front**, in front: nothing dims.
- [ ] With the brightness schedule on, stay away across a point's time: coming back sets the point's level, not the old one.
- [ ] Quit while dimmed: the displays come back first.
- [ ] Hidden displays stay as they are. External monitors dim through their colors (their own menu still shows the same brightness); the laptop panel really dims; an HDR display dims only if its slider says "SDR content brightness".

## 7. Brightness schedule

Settings > Brightness > **Change brightness by time of day**:

- [ ] Each preset fills in its times and transition; editing one switches the preset to Custom. The line under the schedule shows the current level and the next change.
- [ ] The strip above the schedule is darker where the schedule dims, with a line at now; editing a level or time changes it at once. Turning the schedule off hides it.
- [ ] A point a couple of minutes ahead: every display changes then (the log says "Brightness schedule: N% …"), gradually over the transition.
- [ ] Move a slider after a point: your level stays until the next point, also across sleep and restarting Winlight.
- [ ] Sleep through a point or two: only the latest applies, once.
- [ ] A sunrise or sunset point with a Night Light location: the time matches a table. Without a location, the line says 06:00 and 18:00 are used.
- [ ] A monitor asleep or not answering at a point gets the level once it answers.

## 8. Changes, sleep and other tools

- [ ] Unplug an external monitor: within a few seconds the panel no longer lists it. Plug it back in: it reappears within about 10 s, working.
- [ ] Change resolution or one display's scaling: night light stays applied (re-applied within about 1 s).
- [ ] Sleep for over a minute and wake: night light is still applied, and brightness works on every monitor within about 30 s. The log shows "Windows: suspending", "Windows: resumed" once, the re-detection passes ("After waking +5 s: …") and a "Wake summary". **Send these lines even when everything works.**
- [ ] Hibernate and resume: the same.
- [ ] Lock and unlock (Win+L) with night light on: night light is back at once, with no visible flash of normal colors.
- [ ] Let Windows turn the screens off, then wake them: "Windows: display off" and "display on" in the log, nothing sent while off, displays detected again after.
- [ ] **Keep each display's color calibration** on, with a calibration loaded: after the screens turn off and on, and after sleep, the log says "Windows dropped the color calibration of …; putting it back", and the colors are calibrated at once.
- [ ] Start `python main.py` a second time: no second tray icon; the first copy's panel opens.
- [ ] Windows Night Light on: within about 10 s the panel and Settings show "Windows Night Light is on too", and the button opens Windows' Night light page. If the notice never appears, export `HKCU\Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\default$windows.data.bluelightreduction.bluelightreductionstate` with regedit, once with it on and once off, and send both.
- [ ] f.lux running: the log notes the ramp being changed by something else, then warns that "another program keeps changing the colors"; the screen shows f.lux's colors without flickering. Quit f.lux: Winlight's night light is back within about 2 minutes.
- [ ] Twinkle Tray, Monitorian or PowerToys Power Display running at the same time: note whether any monitor misbehaves.
- [ ] A game in exclusive fullscreen (and one borderless, and a fullscreen video), then start Winlight again: the panel does **not** appear and the game keeps focus ("Not opening the panel over a fullscreen app"). Unticking Settings > General > "Never open over fullscreen apps" lets it open.

## 9. Settings, displays and the command line

- [ ] Light and dark mode, and each **Theme** and **Accent color** choice: all text readable, the Apply button's text readable on every accent, nothing cut off, the wide fields ending on one vertical line.
- [ ] Two monitors with different scaling (100% and 150%): the panel opens at the right place and size on the one with the taskbar.
- [ ] Switching Schedule between Always off, Always on, Sunset to sunrise and Custom times shows and hides rows without gaps; a page scrolls only when it is taller than the window. Tab reaches every control.
- [ ] Change something in Settings and close the window with its ✕: it asks to apply or discard. Cancel keeps the window open; Discard and reopening shows the setting as it was. With changes still unsaved, quit Winlight from the tray: it quits without asking.
- [ ] Click a switch: no white ring stays round it. Press Tab to reach one: the ring shows.
- [ ] Narrator (Ctrl+Win+Enter): Tab through Settings and the panel: every control is read with a name ("Schedule, combo box", "DELL brightness, slider"), none as just "button" or "slider".
- [ ] Settings > Displays: a display dimmed in software says its backlight isn't dimmed; in clone mode (Win+P > Duplicate), each display says it shares night light with the other.
- [ ] Settings > Displays: rename a display: the panel, `--list` and the diagnostics use the new name; clearing it brings back its own. Hide a display: it's gone from the panel and "Change all displays together", and the schedule, idle dimming and restores leave it alone.
- [ ] The [command line](command-line.md): `--list`, `--list --json`, `--get --display 1`, `--set 40`, `--set +10 --display 2`, `--set 50 --display <part of a name>`, `--set +10 --panel`, `--night-light on|off|toggle|auto|status`, `--refresh`, `--diagnostics`. Errors say why and exit with 1 (`--display 9`, `--set bright`); with Winlight not running it exits with 2.
- [ ] Settings > **Shortcuts**: add one, click its field and press Ctrl+Alt+Up; set it to "Brighter by" 10, Apply: it says "Works", and pressing it raises every display by 10%, with a note at the bottom of the screen. Holding it keeps stepping. Add one with keys another app uses (Ctrl+Alt+Del can't be recorded; try one your other tools register): it says "Windows or another app has these keys"; quit that app and within 30 seconds it says "Works". A shortcut for one display changes only that display. Over a game in exclusive fullscreen, pressing a shortcut still works, but no note appears and the game keeps focus.
- [ ] Shortcuts on other keyboards and in other situations:
  - [ ] AZERTY (French): record Ctrl+Alt+Shift+A and press the key labelled A: it runs. Switch to the US layout: the key labelled Q runs it.
  - [ ] German layout: record Ctrl+Alt+E: Settings warns about AltGr. Apply, then type AltGr+E in Notepad: no € while it's registered. Remove it: € types again.
  - [ ] NumLock on, record Ctrl+Alt+Num8 ("Num8"); turn NumLock off: pressing it doesn't run (the key now sends Up). Recording with NumLock off gives "Up".
  - [ ] Hold a brightness shortcut on the real keyboard for 3 seconds: about 10 steps a second, typing elsewhere doesn't lag.
  - [ ] A game in exclusive fullscreen, then a borderless one: shortcuts change brightness and night light; no note over the exclusive one; neither loses focus or minimizes.
  - [ ] Another app holding a combination (AutoHotkey, PowerToys): start Winlight first, then the other app: the other app can't have it. The other way round: "Windows or another app has these keys", until that app quits.
  - [ ] Sleep and wake, lock and unlock, sign out and in: shortcuts work afterwards without opening Settings. While locked they do nothing.
  - [ ] Remote Desktop into the PC: shortcuts run in the remote session.
  - [ ] Restart Windows Explorer (Task Manager): shortcuts still work.
  - [ ] In Settings, click a shortcut's field and press Alt+F4: note whether Settings closes or "Alt+F4" is recorded (Windows refuses to register it either way).
  - [ ] An external DDC/CI monitor: hold a brightness shortcut: it steps smoothly and the monitor keeps answering.
- [ ] Take screenshots of the panel and the settings window in both themes.

## 10. Diagnostics and privacy

- [ ] Tray > Report a Problem…: a zip in `%LOCALAPPDATA%\WinLight\Reports` with summary.txt, settings.json and the logs; the summary on the clipboard; Show File opens the folder with the zip selected; Open GitHub Issues opens the issue page.
- [ ] Open `WinLight.log` and the zip: your Windows user name, computer name and email don't appear anywhere (look for `<user>`, `<computer>`, `<home>` instead), nor your city, coordinates, custom display names or listed apps.
- [ ] The log has no line saying a gamma ramp call "hasn't returned". If it has one, the display driver held Winlight up: send the log, with what was happening (waking, a game starting, a driver update).
- [ ] If a monitor ever freezes Winlight: end it in Task Manager and start it again. That display shows "Skipped: Winlight stopped while talking to this display last time"; ⟳ tries it again.

## 11. The installed app

With a build from [Releases](https://github.com/Arnie14/WinLight/releases), or the Actions tab's `winlight-windows` artifact. Quit any copy run from source first.

- [ ] Run `Winlight-<version>-setup.exe`. SmartScreen may warn; note whether it does. There is **no administrator prompt**; it installs to `%LOCALAPPDATA%\Programs\Winlight`. The first page explains the beta and what clashes.
- [ ] The installer, the Start menu entry and `Winlight.exe` show the Winlight moon icon. `Winlight.exe` > Properties > Details: product name Winlight, a numeric file version (for example `0.7.5.2001`) and the product version (`0.7.5-beta.1`).
- [ ] "Launch Winlight" starts it: tray icon only, no console window. The taskbar button (with Settings open) shows Winlight's icon, not Python's.
- [ ] Settings > Location: the city list is filled (the time zone table was bundled). The app looks like the source version.
- [ ] The app folder has `LICENSE.txt` and `THIRD_PARTY_NOTICES.txt`; Settings > General > About > View notices opens the notices.
- [ ] **Start Winlight when I sign in** was ticked in the installer: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` has `Winlight` = `"…\Programs\Winlight\Winlight.exe"`, and it starts after signing out and in. Untick it in Settings and Apply: Task Manager > Startup apps shows it Disabled, and `…\Explorer\StartupApproved\Run` has a `Winlight` value starting with `03`. Restarting Winlight changes neither key. Windows Security > Protection history shows nothing for Winlight.
- [ ] Upgrade with night light on: the running copy quits, the colors go back to normal before files are replaced, and settings are kept. From 0.2.0 or earlier, `%LOCALAPPDATA%\night-light` becomes `%LOCALAPPDATA%\WinLight`.
- [ ] Uninstall from Settings > Apps: Winlight quits first (colors back to normal); its files, Start menu entry, Run and StartupApproved values are gone; with "Add winlight-cli to PATH" ticked at install, its PATH entry is gone and the rest of PATH is as it was. It asks whether to delete the settings too: Yes (the default) removes `%LOCALAPPDATA%\WinLight`, No keeps it, and a silent uninstall (`unins000.exe /VERYSILENT`) removes it. Upgrading over an installed version keeps the settings. With Windows' color limit unlocked, it also asks whether to put the limit back (No by default); Yes shows the administrator prompt and removes `GdiIcmGammaRange`.
- [ ] Portable zip: unzip to another folder and run `Winlight.exe`: it works the same. Turning on "Start Winlight when I sign in" there adds a Run value for that copy.
- [ ] Note the installer's size, and how long the app takes to start.

## What to send back

- The zip from **Report a Problem…** (or `--diagnostics`): the log, settings, `probe.txt` if you ran `--probe`, the compatibility report and a summary of every display.
- The output of `tools/hardware_checks.py`, and of `pytest` if anything failed.
- The screenshots.
- The failing checklist items, with what happened instead.
