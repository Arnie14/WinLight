# Plan: Winlight 0.8.0

The work for 0.8.0, in three betas so each part is tested before the next. Written 2026-11-04. The MSIX details are in [msix-package.md](msix-package.md).

## Beta 1: audit and groundwork

1. **A precise audit of the code**, module by module, riskiest first: the native Windows code (`hardware/win32.py`, `hardware/winsystem.py`), the backends and time limits (`hardware/windows.py`, `hardware/calls.py`), the monitor queue (`brightness/monitors.py`), the night light controller, the system parts, then the UI. Each is checked against the design rules in [development.md](../development.md) and [windows-notes.md](../windows-notes.md). Small fixes are made with a regression test each; larger findings are reported for a decision.
2. **Packaging groundwork**, with no change to today's builds: one `is_packaged()` check, and one function that turns a path in the data folder into the one Explorer sees (a package's data folder is redirected). Report a Problem's Show File, Open folder and printed paths go through it.
3. **Night light on screen before display detection** at start: up to about 0.8 s sooner after sign-in, in both builds.
4. **A welcome screen**, once at the first start and never over a fullscreen app: turning off Windows Night Light, when night light turns on, DDC/CI for external monitors; f.lux, LightBulb, Twinkle Tray, Monitorian and Windows Night Light detected (read-only) with a tip each and a link to the switching guide; Open Settings or Done; reachable again later.

## Beta 2: the MSIX package

5. Package-only behavior behind `is_packaged()`: no warmer-colors unlock (the Store allows no elevation), no update check, no taskbar app id, restart after an update.
6. Start at sign-in through a startup task, with its five states.
7. Noticing the installer build, and importing its settings.
8. Manifest, assets, `build.py --msix`, a test-signed package checked on the test laptop, and the Windows App Certification Kit.
9. Two versions from one codebase: version mapping, both built by the release workflow, differences in the changelog.

## Beta 3: signing and a faster start

10. Code signing for the installer build: the SignPath Foundation (free for open-source projects; the publisher shown is "SignPath Foundation"), or a paid certificate.
11. Once signed, start at sign-in through a scheduled task (about 5–7 s sooner, to verify).

## Decided

- Three betas (2026-11-04).

## To decide before Beta 2 and 3

- How to call the startup task API from Python: the `winrt-…` packages, a COM binding through ctypes, or a native helper.
- The Partner Center account, early, to reserve the name.
- Signing: SignPath, a paid certificate, or unsigned until 1.0.0.
- A private-audience Store submission at the end of 0.8.0, or the first submission at 1.0.0.
