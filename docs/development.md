# Development

Winlight is a Windows app written in Python with Qt (PySide6). This page covers running it from source, testing, building and releasing, and where things live in the repository. How the Windows backend works, and why, is in [windows-notes.md](windows-notes.md).

## Built with

| Purpose | Tool |
|---|---|
| Language | Python 3.12+ |
| GUI | PySide6 (Qt for Python) |
| External monitor brightness | DDC/CI through Windows' Monitor Configuration API (`dxva2`), via `ctypes` |
| Display names, connectors, HDR state | `QueryDisplayConfig`, via `ctypes` |
| Laptop panel brightness | `wmi` (WMI `WmiMonitorBrightness`) |
| HDR displays | Windows' SDR white level (`DisplayConfigSetDeviceInfo`), via `ctypes` |
| Night light, software dimming | Windows gamma ramps, via `ctypes`, one composed ramp per display |
| Sunrise and sunset | `astral` |
| Settings | JSON in `%LOCALAPPDATA%\WinLight` (`platformdirs`) |
| Packaging | PyInstaller, Inno Setup |

## Running from source on Windows

Python 3.12 or newer, from [python.org](https://www.python.org/downloads/windows/):

```powershell
git clone https://github.com/Arnie14/WinLight.git
cd WinLight
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python main.py
```

Create `.venv` on the machine that uses it: a virtual environment copied from Linux (or the other way round) doesn't work.

Useful options (`python main.py --help` lists them all):

- `--debug`: verbose logging. The log is also written to `%LOCALAPPDATA%\WinLight\Logs\WinLight.log`.
- `--probe`: prints what each Windows API reports about every display and saves it as `probe.txt` in the log folder. It changes nothing, except that each display is briefly tinted to find the warmest night light Windows allows. Use it when a monitor misbehaves.
- `--report`: prints the compatibility report (also in Settings > Displays) and saves it as `compatibility.txt`. It sends nothing to the displays.
- `--quit`: asks the running copy to quit cleanly, restoring normal colors. The installer uses it before upgrading or uninstalling.
- `--diagnostics`: saves the same zip as Report a Problem and prints its path.
- `--allow-multiple`: lets a second copy start (normally a second launch opens the running copy's panel).
- `--config PATH`: a settings file to use instead of the default.
- The [command-line options](command-line.md) work from source too: `python main.py --list`.

## Backends

The hardware layer sits behind small interfaces, chosen with `--backend`:

| Backend | Used for |
|---|---|
| `real` (the default on Windows) | DDC/CI, WMI, SDR brightness and gamma ramps |
| `fake` | Pretend monitors and a logged "gamma", no hardware needed |
| `kde` (the default on a KDE Plasma desktop) | Plasma's brightness and Night Light services, so the UI can be developed on Linux |

Winlight targets Windows. On Linux, `pip install -e ".[dev]"` installs the `kde` backend's dependencies, and most of the code and tests run there, but the Windows backends can only be checked on Windows.

## Tests and lint

```powershell
pytest -n auto --dist loadgroup      # the whole suite, on every core: about 2 minutes on the test laptop
pytest -n auto -m "not slow"         # while working: everything but the slow tier
ruff check .
```

- **Run everything before committing and before a release**; CI runs everything on every push. `-m "not slow"` leaves out the slow tier (soaks, random properties, mutation checks and runs of the suite inside a test, listed in `SLOW` in `tests/conftest.py`), about half the time in a tenth of the tests. `pytest` without `-n` runs the same tests one at a time, in about 8 minutes, and a single file or test is quickest that way.
- **Running in parallel** (pytest-xdist) spreads the tests over several processes. Tests that use something there is one of per desktop (real hotkeys and key presses, in `DESKTOP_WIDE` in `tests/conftest.py`) stay together on one worker, so `--dist loadgroup` matters. A test that fails only in parallel depends on another test or on timing: that's a bug to find, not a reason to run it alone (running in parallel found a race in the monitor service before 0.8.0).
- **Garbage collection after each test** (`conftest.py`) deletes the test's Qt objects on the main thread. Everything that exists once the tests are collected is frozen first (`gc.freeze()`), so each collection looks only at what tests made since: that took the suite from 19 to 8 minutes before running in parallel.
- The suite runs the Windows backends against a fake of the Windows APIs, plus Windows-only tests of the real bindings: structure sizes and field offsets, `QueryDisplayConfig`, EDID identity, gamma ramps, DDC/CI handles, power notifications in a real window, the named pipe's ownership check. On Windows, the only expected skip is the Linux-only KDE backend's import.
- `tests/test_imports.py` parses every import of the app's own modules, so a moved module or renamed name fails at once.
- `tests/test_docs.py` lints the Markdown documents: headings, links and anchors that resolve, tables with matching columns, and the project's writing rules.
- `tests/test_architecture.py` checks the design's rules in the source (declared Windows call types, no signals under a lock, named daemon threads, no sleeping or nested event loops on the main thread, owned timers, atomic writes, and more); a justified exception goes in its list with the reason. `tests/test_design.py` and `tests/test_concurrency_and_soak.py` check the design's promises with random cases from fixed seeds, so a failure repeats exactly.
- `tests/test_concurrency.py` stages races one interleaving at a time: `tests/fake_windows.py` provides a fake clock, a scriptable fake of every Windows call the backends make, and gates that hold a thread inside a call until the test lets it go. `pytest -m concurrency` runs just these. They never sleep (`test_architecture.py` enforces it), so they don't depend on the machine's speed.
- `tests/test_gamma_properties.py` and the end of `tests/test_icc.py` are property tests (hypothesis): each states what must hold for every input, and hypothesis searches for a counter-example, shrunk to the smallest one. They run the same cases every time (the profile in `conftest.py`).
- `tests/test_frontend_audit.py` checks every control in Settings and the panel for a name a screen reader can say, and other rules for the windows.
- `tests/test_fault_injection.py` breaks what the gamma backend relies on (its journal file, Windows' display query) and checks each fault costs at most that piece of information. `tests/test_ddc_retries.py` follows a garbled DDC/CI message through the real retry loop, backend and queue.
- `tests/test_mutations.py` checks that the tests guarding the most important safeguards fail when a safeguard breaks: each case copies the source to a temporary folder, breaks one safeguard there (never in the working tree) and runs its tests. When a safeguard's code is rewritten, its case says so; write its break again for the new code. Tools such as mutmut need `fork()`, which Windows doesn't have.
- `pytest -m concurrency`, or a single file, is quicker still while working on one part.
- `tests/conftest.py` fails a test that raises inside a Qt slot, makes Qt print a warning, leaves a non-daemon thread running, or raises in a thread or a finalizer; a test running past 300 s ends the run with every thread's stack (`WINLIGHT_TEST_WATCHDOG_S` changes it). `tests/test_suite_guards.py` checks each guard. A new setting must be added to `EVERY_SETTING` in `tests/test_design.py`.
- Ruff's rules are in `pyproject.toml` under `[tool.ruff.lint]`, and the pytest markers under `[tool.pytest.ini_options]`. CI runs both on every push and pull request, and reports each run's test counts in its summary.

## Checks on real hardware

```powershell
Winlight.exe --quit          # if Winlight is running: it would re-apply its own colors
python tools/hardware_checks.py
```

`tools/hardware_checks.py` drives the real ctypes bindings, dxva2, WMI and GDI gamma on the PC it runs on: display configuration and identity, DDC/CI error handling (read-only), WMI brightness on a laptop panel, night light, Windows' limit on warm ramps, calibrations, software dimming, the `--probe` report, pausing, the idle layer, crash recovery after a killed process, safe mode, and the system queries. It tests the built-in panel if there is one, otherwise the first display, and skips what doesn't apply. It puts the colors and the panel's brightness back at the end. The test plans in [windows-testing.md](windows-testing.md) and [testing-installer.md](testing-installer.md) cover what needs a person at the screen.

## Building the Windows app

With [Inno Setup 6](https://jrsoftware.org/isdl.php) installed (or a copy in an `Inno Setup 6` folder next to the project):

```powershell
pip install -e ".[dev,build]"
python packaging/build.py
```

This writes `dist\Winlight\` (the app, with `LICENSE.txt` and `THIRD_PARTY_NOTICES.txt`), `Winlight-<version>-portable.zip`, `Winlight-<version>-setup.exe` and `SHA256SUMS.txt`, the SHA-256 checksum of each download in the format `sha256sum -c` reads. The release workflow publishes `SHA256SUMS.txt` with the files, and lists the checksums on the release page and in the run's summary. The build smoke-tests the frozen app and `winlight-cli.exe` before packaging. [`packaging/`](../packaging/) holds the PyInstaller spec, the Inno Setup script, the installer's information page and the icon generator; `tools/third_party_notices.py` writes the notices from the installed packages' own license files, with the texts they don't ship kept in `packaging/licenses/`.

The README screenshots come from `python tools/screenshots.py` (demo displays, light and dark); run it on Windows for the native look.

## Versions and releases

- **Versions** are `MAJOR.MINOR.PATCH`, optionally followed by `-alpha.N`, `-beta.N`, `-rc.N` or `-dev`, set in `nightlight/__init__.py`. Windows' file version takes four numbers; the fourth orders pre-releases before their release: `alpha.N` is 1000 + N, `beta.N` 2000 + N, `rc.N` 3000 + N, the release 9000 and a dev build 0. So `0.3.0-beta.1` is file version `0.3.0.2001`, and the product version keeps the readable form.
- **The installer's AppId** (`packaging/winlight.iss`) never changes: upgrades and the uninstaller find the installed copy by it, and a test pins it.
- **Releasing:** push a tag such as `v0.3.0-beta.1`. GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml)) lints, tests, builds on Windows and publishes a release titled "Winlight 0.3.0 Beta 1". Tags with `-alpha`, `-rc` or `-dev` become pre-releases. A push to `main`, or running the workflow by hand, builds the files as a downloadable artifact without a release.
- **Every other push and every pull request** is linted and tested on Windows by [`.github/workflows/tests.yml`](../.github/workflows/tests.yml), without building; failures show as annotations on the pull request.
- [CHANGELOG.md](../CHANGELOG.md) records each version's changes.

## Repository layout

```text
main.py                     entry point: command line, logging, startup
pyproject.toml              dependencies (with dev and build extras), Ruff and pytest settings
CHANGELOG.md                changes in each version
LICENSE                     GNU GPL v3.0
nightlight/
  app.py                    wires the services to the UI
  config.py                 reading and saving the settings (their JSON file), and the data folder
  files.py                  atomic writes
  gc_guard.py               garbage collection on the main thread
  core/                     pure logic, no Qt, hardware or files: settings (the settings model), colortemp
                            (ramps, limits), schedule (night light), brightness_schedule (and presets), clock
                            (daylight saving), edid, icc (calibrations in color profiles), locations, shortcuts
                            (key names and rules)
  hardware/                 backend interfaces (brightness, gamma), windows + win32 (the Windows display APIs),
                            winsystem (foreground app, power and session events, the pipe's owner, Windows
                            Night Light), calls (time limits), safe_mode (skipping a display that crashed),
                            kde (Linux development backend)
  brightness/               monitors (the one queue of monitor calls, on a worker thread), memory (remembered
                            levels), scheduler (the brightness schedule), idle_dim, keys (the laptop-key
                            follower), power_source (plugging in and unplugging), wake_report (re-detection
                            after waking)
  color/                    controller (night light on the displays), exemptions (pausing per display)
  system/                   autostart, single_instance (one copy, and the command-line pipe), watcher (display
                            changes, sleep), shortcuts (registering and running them), updates (the optional
                            update check), apps (installed apps from the Start menu, for the app lists),
                            packaging_info (whether it runs from the Store package, and the paths others see)
  support/                  diagnostics (Report a Problem), privacy (scrubbing), compat (compatibility report),
                            probe (--probe)
  cli/                      client (winlight-cli) and commands (what the app does for it)
  ui/                       tray, flyout, settings window and its parts, schedule editor, day_ribbon (a day of
                            night light or brightness), the preview note, shortcut_editor and shortcut_overlay,
                            theme, icons, welcome (the welcome screen)
  data/                     time zone table for picking a location (from tools/make_timezones.py)
packaging/                  PyInstaller spec, Inno Setup script, installer notes, licenses, build.py, icon
tools/                      hardware_checks.py, third_party_notices.py, screenshots.py, make_timezones.py
tests/                      pytest suite; fake_windows.py (a scriptable fake of the Windows display calls, a
                            fake clock and gates, for the concurrency tests)
docs/                       features, why-winlight, command-line, windows-notes, test plans, development;
                            history/ (earlier reports); plans/ (work not started yet: msix-package); screenshots/
.github/workflows/          release.yml: lint, test, build and publish; tests.yml: lint and test other pushes and pull requests
```

Settings, state and logs live in `%LOCALAPPDATA%\WinLight` (`Logs\` for the log, `probe.txt` and `compatibility.txt`, `Reports\` for Report a Problem zips).

## Writing for this project

Documents are written for the people who use and build Winlight: plain, specific and technical, without marketing language. The test hardware is "the test laptop". Third-party projects are described from their own documentation, with sources.
