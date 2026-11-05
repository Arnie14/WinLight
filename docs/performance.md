# Performance

How much Winlight asks of your PC. Measured on the test laptop (Intel Core i7-8750H, 6 cores, 16 GB of memory, Windows 11 25H2) with Winlight 0.8.0 Beta 1, after it had settled, with night light on, automatic pausing and dimming when idle turned on.

| | |
|---|---|
| Memory | About 50 MB of its own (private bytes); about 90 MB including what it shares with Windows |
| Processor, while idle | About 0.5% of one core: 0.05% of the whole processor |
| Threads | 6 |
| Start-up | Night light on screen about 0.5 s after starting; displays found about 1.5 s after |
| Download | The installer is about 25–30 MB |
| On disk | About 80 MB installed; settings, state and logs in `%LOCALAPPDATA%\WinLight`, the log at most 3 MB |
| Network | None, unless you turn on Check for updates: then one request to GitHub a day |

A tester's PC with a DDC/CI monitor showed the same picture over two weeks of Winlight running without a restart: its log grew by about 15 KB a day.

## What it does while idle

Nothing is sent to the displays while nothing changes. External monitors are talked to over DDC/CI only when a display is connected, wakes or turns on, when you move a slider or press a shortcut, and when a schedule point comes. What runs in the background is a handful of light checks:

| Every | What | Why |
|---|---|---|
| 0.4 s | Which app is in front | Pausing night light for fullscreen, listed or media apps; not at all while pausing is off, every 10 s while the displays are off |
| 1.5 s | Whether Windows reset the colors | Windows and some apps reset the screen's colors (unlocking, waking, games); every 30 s while the displays are off |
| 1 s | Python's memory clean-up | Done on the main thread only, for stability; a full one, once a minute, takes about 10 ms |
| 5 s | The clock | Noticing sleep and waking, even when Windows doesn't say |
| 10 s | Night light's schedule, and Windows Night Light's setting | Night light moves in small steps during a transition; the notice that the two tints would stack |
| 1 minute | The brightness schedule | Brightness moves in small steps during a transition |

While dimming when idle is waiting, it checks for input every 5 s, and every 0.3 s once the displays are dimmed, so the first key or mouse move brings them back at once. "External displays follow the laptop's brightness keys" reads the laptop panel's level every 2 s while it's on.

## How it is kept light

- **No DDC/CI polling.** Monitors aren't asked for their brightness on a timer: DDC/CI is slow (tens of milliseconds a call), and some monitors misbehave when asked constantly.
- **Calls with time limits, on their own threads.** A monitor or driver that hangs never freezes the tray icon or the panel.
- **Windows' own notifications** for sleep, waking, displays turning on and off, and display changes, instead of watching for them.
- **Windows built once.** Settings and the welcome screen are built the first time they are opened; the panel is built at start, so the tray icon opens it at once.
- **A smaller build.** Qt's QML and Quick engine, its PDF module and virtual keyboard are left out of the app folder: a widgets app never loads them, and they would make it well over 100 MB.

Winlight is written in Python with Qt, which takes more memory than an app written in C++ alone; most of the 50 MB is Qt and Python themselves.

## Measuring it yourself

Task Manager's Details tab shows `Winlight.exe`'s memory and CPU. Its log, in `%LOCALAPPDATA%\WinLight\Logs`, shows when each display was found and how long each detection after waking took.
