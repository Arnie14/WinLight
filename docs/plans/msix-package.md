# Plan: an MSIX package for the Microsoft Store

A plan, not a feature: nothing here is built yet. It records what a Microsoft Store (MSIX) version of Winlight needs, what changes in the code, what can go wrong, and how to test it, so the work can start from it later. Written 2026-10-29, against 0.6.0 Beta 1; checked again for 0.7.5 Beta 1 (2026-10-30), whose changes don't alter it. The app picker reads Start menu shortcuts through `WScript.Shell`, which works in a full-trust package; test it there (to verify). The version numbers below are examples: the package is planned for 0.8.0.

## How to use this plan

To build it with Claude Code, start a session in the repository with a prompt such as:

> Read docs/plans/msix-package.md and implement the MSIX build in the order of its "Work plan" section. Keep the Inno Setup installer and the portable zip working exactly as they are: every packaged-only behavior goes behind `packaging_info.is_packaged()`. Reference LightBulb's and Twinkle Tray's code first for anything they already do. Stop and ask before any step marked "decide".

Every "decide" below is a choice to make first. Everything marked "to verify" is an assumption that no one has tested yet; test it on the test laptop before relying on it.

## Why the Store

| | Inno Setup installer (now) | MSIX in the Store |
|---|---|---|
| Signing | Unsigned: SmartScreen warns on every download | The Store signs the package; no warning |
| Updates | Manual (the optional update check only points to GitHub) | The Store updates it |
| Cost | None | A Partner Center developer account (sources disagree: free, or a one-time fee of about $19 by country) |
| Install location | `%LOCALAPPDATA%\Programs\Winlight` | `C:\Program Files\WindowsApps\…`, a new folder for each version |
| Settings | `%LOCALAPPDATA%\WinLight` | Redirected to the package's private folder (below) |
| Start at sign-in | Run key, written by the installer | A startup task declared in the manifest |
| Uninstall | The uninstaller, which asks about settings | Windows removes the package and its private data, without asking |

The Store signs MSIX packages for free; an `.exe` or `.msi` submitted to the Store instead must already be signed with a certificate from a trusted authority (about $150–300 a year for an individual outside the US and Canada). MSIX is therefore the free route to signed builds.

## What other apps did

- **Twinkle Tray** builds an AppX with electron-builder next to its NSIS installer, for x64 and ARM64. Its manifest adds an execution alias (`Twinkle-Tray.exe`, so the command line works) and the auto-launch extension. In the code, one flag (`isAppX`) changes behavior: start at sign-in uses its own startup helper instead of the Run key, the GitHub update check is skipped entirely, and so is its geolocation lookup. Its settings path is the same in both builds (the app data folder, redirected by Windows in the package).
- **Monitorian** (a .NET app in the Store) detects packaging with `Package.Current` (an error `0x80073D54`, APPMODEL_ERROR_NO_PACKAGE, means unpackaged), then picks one of two startup workers: a StartupTask for the package, the Run key otherwise. Its StartupTask code requests enabling only from the Disabled state; when the user turned it off in Task Manager (DisabledByUser) it doesn't ask again, since Windows won't let it. Policy states (DisabledByPolicy, EnabledByPolicy) need handling too, which Monitorian's code doesn't.
- **LightBulb** isn't in the Store; nothing to borrow for packaging.

## Microsoft's rules that matter here

From "Prepare to package a desktop application" and the Store policies (version 7.20):

1. **No elevation, for any feature.** Apps that require elevation for any part of their functionality aren't accepted. "Unlocking warmer colors" runs `reg.exe` elevated to set `GdiIcmGammaRange` in HKLM: it can't be in the Store build.
2. **No starting command-line utilities** such as `cmd.exe`, PowerShell or `reg.exe` (they don't run in S mode, and every Store app must work there). Again "Unlocking warmer colors". Opening Explorer to show a file is an inbox app, not a command utility: keep it, but test it (to verify).
3. **HKLM is read-only, HKCU writes are private.** Writes to HKCU go to a private per-package copy, invisible to Windows. So the Run key can't start a packaged app. Reads of the real registry still work (Windows Night Light's state, `GdiIcmGammaRange`, StartupApproved).
4. **AppData writes are redirected** to `%LOCALAPPDATA%\Packages\<package family name>\LocalCache\Local\…`, and removed on uninstall. The app's own file calls see the usual path; other programs (Explorer, Notepad, a user's file manager) see only the real one.
5. **No writing to the install folder.** Winlight doesn't (logs and settings are in the data folder): keep it that way.
6. **No custom AppUserModelID.** `SetCurrentProcessExplicitAppUserModelID` may only be given the ID the package defines: skip the call when packaged.
7. **The working directory** isn't the one a shortcut would give. Winlight doesn't rely on it (check `third_party_notices()` and other relative paths).
8. **Clean uninstall** (policy 10.2.7). Nothing the app creates outside the package may be left behind, so no scheduled tasks or real-registry entries.
9. **Changing Windows settings needs consent and supported, documented methods** (10.2.8). Brightness and gamma ramps are Winlight's purpose and use documented APIs. Reading Windows Night Light's undocumented CloudStore state only reads, to show a notice; say so in the certification notes.
10. **No dynamic code** (10.2.2): no downloading and running anything. The update check must be off in the Store build (the Store updates the app).
11. **A privacy policy URL** is required if the app accesses, collects or transmits personal information (10.5.1). With the update check off, the Store build connects to nothing; publish a short privacy page anyway, since the listing asks.
12. **Restricted capability `runFullTrust`.** Every packaged Win32 app declares it; the submission explains why (gamma ramps, DDC/CI, WMI, hotkeys, tray).
13. **Version numbers.** MSIX versions are `Major.Minor.Build.Revision`, and the Store requires Revision 0. Winlight's file version puts the beta in the fourth number (`0.6.0.2001`): decide a mapping, such as `0.6.2001.0` for 0.6.0 Beta 1 and `0.6.3000.0` for 0.6.0, that always increases. A Store update must have a higher version than the one installed.

## What changes in the code

Everything goes behind one check, so the installer and portable builds don't change.

### 1. Knowing it's packaged (new: `nightlight/system/packaging_info.py`)

- `is_packaged()`: call `GetCurrentPackageFullName` (kernel32) through ctypes with declared types; `APPMODEL_ERROR_NO_PACKAGE` (15700) means not packaged. Cache the answer.
- `package_family_name()`: `GetCurrentPackageFamilyName`, for the real data folder path (section 3).
- No WinRT dependency needed for this part.

### 2. Start at sign-in (`nightlight/system/autostart.py`)

Now: the installer writes the HKCU Run value; the setting switches it on and off through `StartupApproved\Run`, as Task Manager does.

Packaged: a `windows.startupTask` in the manifest (`TaskId="WinlightStartup"`, `Enabled="true"`), and the setting uses the StartupTask API:

- States: Enabled, Disabled, DisabledByUser, DisabledByPolicy, EnabledByPolicy. Turning on calls `RequestEnableAsync()` only from Disabled. From DisabledByUser Windows refuses: Settings says "Turned off in Windows Settings > Apps > Startup" and opens `ms-settings:startupapps`. The policy states show as fixed, with the toggle disabled.
- Calling it from Python needs WinRT: the `winrt-Windows.ApplicationModel` packages from PyPI (decide: add that dependency, or a small C++/C# helper, or the raw COM interfaces through ctypes). Twinkle Tray uses a native helper of its own.
- A startup task is off until the app has run once, unless `Enabled="true"` in the manifest; Windows still lists it in Startup apps where the user can turn it off.
- `--startup`-style detection: the app needs to know when Windows started it at sign-in (for "Start minimized"). A startup task can pass no arguments; detect it from the activation kind (WinRT `AppInstance.GetActivatedEventArgs`, StartupTask kind), or treat any launch within 2 minutes of sign-in as a sign-in start (to verify which works from Python).

Sign-in timing: startup tasks are started by Explorer's startup-app queue, like the Run key, so a packaged Winlight starts as late as now (about 6–8 s after sign-in on the test laptop). The faster scheduled-task approach can't be used in the package: the task would outlive the uninstall (policy 10.2.7). See "Start-up speed" below.

### 3. The data folder (`nightlight/config.py: data_dir()`, and everything that shows a path)

The app keeps reading and writing `%LOCALAPPDATA%\WinLight` as now; Windows redirects it. What breaks is every place that hands the path to someone else:

- Report a Problem's "Show File" runs `explorer /select,<path>`: Explorer would look in the real folder and find nothing. Translate to `%LOCALAPPDATA%\Packages\<family name>\LocalCache\Local\WinLight\…` when packaged.
- Settings > General > Log files > Open folder, the third-party notices, and the dialog text that names the Reports folder: same translation.
- `--report`, `--diagnostics` and the log line "Log file: …" print paths: print the real one.
- Decide: move the data folder translation into one function (`config.visible_path(path)`) and use it everywhere a path leaves the app.

Moving from the installer build to the Store build:

- The two builds don't share settings: the package sees its private folder first. Whether a packaged app reading `%LOCALAPPDATA%\WinLight` sees the real folder's files when its private copy has none is to verify. If it does, the first packaged start can copy settings in. If not, offer "Import settings from the installed version" once; decide how the package reads the real folder (a file picker the user points at it always works).
- Both builds installed at once would both run at sign-in and fight over the gamma ramps. The package's first start should notice the installer build (its Run value, or `%LOCALAPPDATA%\Programs\Winlight\Winlight.exe`) and say "Uninstall the other Winlight first", rather than run alongside it. Both use the same single-instance pipe name, so only one can run; make the second say why.
- Opting out of AppData redirection (`desktop6:FileSystemWriteVirtualization` set to disabled) would share the folder with the installer build, but then uninstalling leaves the data behind (against 10.2.7) and both builds write one file. Not recommended.

### 4. Features to turn off or change when packaged

| Feature | File | In the package |
|---|---|---|
| Unlocking warmer colors | `hardware/win32.py: expand_gamma_range`, Settings | Hidden. Settings keeps showing Windows' limit and links to the instructions in windows-notes, for users who set `GdiIcmGammaRange` themselves |
| Check for updates | `system/updates.py`, Settings > General | Hidden and never run; the Store updates the app |
| Start at sign-in | `system/autostart.py` | StartupTask (section 2) |
| Taskbar identity | `main.py: set_app_id()` | Skipped |
| Uninstall question about settings | `packaging/winlight.iss` | Not applicable; the Store listing says uninstalling removes settings |
| `winlight-cli` on PATH | installer task | An execution alias, `winlight-cli.exe` (and `winlight.exe`), in the manifest |
| Installer notes (clashing apps, disclaimer) | `packaging/installer-notes.txt` | The Store description, and a first-start notice |

### 5. Things that work the same (to verify on the package)

- Gamma ramps (`SetDeviceGammaRamp`), DDC/CI (`dxva2`), WMI brightness, SDR white level, `RegisterHotKey`, power and session notifications, the tray icon and its notifications, the named pipe between the app and `winlight-cli` (both inside the package), Qt's network (only in the installer build).
- Reading the real registry: Windows Night Light's CloudStore blob, `GdiIcmGammaRange`, the display profile from `GetICMProfile` (ICC files in `C:\Windows\System32\spool\drivers\color` are readable).
- The crash journal (`gamma.json`) and safe mode files: inside the data folder, so redirected and fine.

### 6. Updates while Winlight runs

The Store updates the package in the background. If Winlight is running, Windows closes it to update. That's a clean close only if Windows sends it a close message (to verify: Restart Manager's `WM_QUERYENDSESSION`/`WM_ENDSESSION`, which `SystemEvents.endingSession` already handles, or `WM_CLOSE`). If it's ended without one, the night light tint stays on screen until the next start, which the crash journal then resets.

Precautions:

- Call `RegisterApplicationRestart` at start (kernel32, with declared types), so Windows starts Winlight again after an update or a crash-free restart.
- Test an update with night light on: the tint must go away (or be put back by the new version) within seconds.
- The install folder's path changes with every version: nothing may store the executable's path (the Run key did; the startup task doesn't). Windows may also forget the tray icon's "show on the taskbar" choice when the path changes (to verify on Windows 11; Qt's tray icon doesn't set a GUID).

## Building it

1. **Partner Center**: create the developer account, reserve the name ("Winlight", or decide another if taken), and note the package identity it gives: `Name`, `Publisher` (CN=…), `PublisherDisplayName`.
2. **Layout**: the PyInstaller one-folder output (`dist/Winlight/`, with `winlight-cli.exe`) plus `AppxManifest.xml` and the visual assets, in one folder.
3. **Visual assets**: Square44x44Logo (with `targetsize-16/24/32/48/256` and `_altform-unplated` variants for the taskbar and tray), Square150x150Logo, Wide310x150Logo, StoreLogo (50×50), and scale-100/200 variants. `packaging/make_icon.py` can render them from the same drawing as `winlight.ico`.
4. **Manifest** (sketch, to complete):

```xml
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
         xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap3 desktop rescap">
  <Identity Name="(from Partner Center)" Publisher="CN=(from Partner Center)" Version="0.6.2001.0" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>Winlight</DisplayName>
    <PublisherDisplayName>(from Partner Center)</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.22000.0" MaxVersionTested="10.0.26200.0"/>
  </Dependencies>
  <Resources><Resource Language="en-us"/></Resources>
  <Applications>
    <Application Id="Winlight" Executable="Winlight.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="Winlight" Description="Brightness and night light for every display"
                          BackgroundColor="transparent" Square150x150Logo="Assets\Square150x150Logo.png"
                          Square44x44Logo="Assets\Square44x44Logo.png"/>
      <Extensions>
        <desktop:Extension Category="windows.startupTask" Executable="Winlight.exe" EntryPoint="Windows.FullTrustApplication">
          <desktop:StartupTask TaskId="WinlightStartup" Enabled="true" DisplayName="Winlight"/>
        </desktop:Extension>
        <uap3:Extension Category="windows.appExecutionAlias" Executable="winlight-cli.exe" EntryPoint="Windows.FullTrustApplication">
          <uap3:AppExecutionAlias><desktop:ExecutionAlias Alias="winlight-cli.exe"/></uap3:AppExecutionAlias>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities><rescap:Capability Name="runFullTrust"/></Capabilities>
</Package>
```

   Windows 11 only (MinVersion 10.0.22000.0), matching what Winlight supports.
5. **Pack**: `makeappx pack /d <folder> /p Winlight-<version>.msix` (Windows SDK). Add it to `packaging/build.py` as an optional step (`--msix`), and to the release workflow as a separate artifact, not a release asset (the Store build goes to Partner Center, not GitHub).
6. **Test-sign for local installs only**: a self-signed certificate whose subject matches the manifest's Publisher, trusted on the test laptop, `signtool sign`, then `Add-AppxPackage`. The Store re-signs the uploaded package; a self-signed package isn't for users.
7. **Windows App Certification Kit**: run it on the package before each submission; it catches most rejections.
8. **Submit**: listing text (what clashes, that DDC/CI must be on in the monitor's menu, that uninstalling removes settings), screenshots from `tools/screenshots.py`, privacy policy URL, age rating, certification notes (why `runFullTrust`; that the CloudStore read is read-only; that no elevation is used). Certification takes up to three business days per release.

## Testing the package

Each item is a check on the test laptop with the test-signed package installed:

- [ ] Installs and starts; the tray icon appears; night light and brightness work on every display, including DDC/CI and HDR checks when such a display is connected.
- [ ] Settings > General: "Start at sign-in" shows the startup task's real state; turning it off and on works; turned off in Windows Settings > Apps > Startup, the toggle says so and links there.
- [ ] Sign out and in: Winlight starts; time from sign-in to the first log line is noted.
- [ ] `winlight-cli --list` works from a new terminal (the alias); `winlight-cli --night-light toggle` reaches the running app.
- [ ] Report a Problem > Show File opens Explorer on the zip; Log files > Open folder opens the real folder.
- [ ] Unlocking warmer colors and Check for updates aren't shown.
- [ ] Keyboard shortcuts register and run; the note never takes focus.
- [ ] The installer build installed too: the package refuses to run alongside it, and says why.
- [ ] Update: install version N, then N+1 with night light on: the tint is right after the update, the startup task stays as it was, settings are kept.
- [ ] Uninstall: the package, its data folder and its startup entry are gone; the screen's colors are normal.
- [ ] The Windows App Certification Kit passes.

## Start-up speed after sign-in (both builds)

Measured on the test laptop (2026-10-29), from Windows' Shell-Core log:

- Sign-in 20:12:10; Explorer starts the Run key's programs at 20:12:16, one at a time, in the order their values were created; two apps ahead of Winlight took about 1 s each; Winlight started at 20:12:18, logged its first line at 20:12:19.1, and found the displays at 20:12:19.9.
- Winlight's own share is about 1.7 s; the rest is Windows.

Options:

| Option | Earlier by | Cost | Notes |
|---|---|---|---|
| First in the Run key | About 2 s on the test laptop (the apps ahead of it) | Not possible cleanly | The order is the values' creation order; moving up means deleting and re-creating other apps' entries, which no app should do |
| A scheduled task at sign-in, instead of the Run key | Expected 5–7 s (to verify: the Task Scheduler log was off) | Installer and `autostart.py` rewritten (below) | Installer build only. Not possible in the Store package (it would outlive the uninstall) |
| Put night light on screen before display detection | Up to about 0.8 s | Small: reorder start-up | Both builds |
| Fewer imports at start | 0.1–0.3 s | Small | Both builds |

No option guarantees no bright moment. Windows shows the sign-in animation and starts the desktop before any app runs, and can reset gamma ramps while it sets up the displays. A scheduled task narrows the untinted time from about 9 s to an expected 2–3 s.

The scheduled task, for the signed installer build:

- **Creating it without administrator rights works** (tested 2026-10-29): `schtasks /create /sc onlogon` is refused for a standard user, but `schtasks /create /xml` with a task limited to the user's own account (`LogonTrigger` with `UserId`, `LogonType` InteractiveToken, `RunLevel` LeastPrivilege) succeeds.
- **Code**: the installer creates the task from an XML template instead of the Run value, and deletes it on uninstall; `autostart.py` enables and disables the task (`schtasks /change /enable|/disable`, or the Task Scheduler COM API) instead of the StartupApproved switch; upgrades remove an old Run value. About 200–300 lines with tests.
- **Risks**: Microsoft Defender treats scheduled tasks created by unsigned programs as a persistence technique, as it did the Run key in 0.1.0 Beta 5; only do it for the signed build. The task isn't listed in Task Manager's Startup apps, so Settings is where users switch it off. Winlight may start before the taskbar exists: the tray icon must be added again when Explorer announces itself (`TaskbarCreated`; to verify that Qt does it).
- **Decide**: whether the signed installer build should switch to the task, given the Defender risk.

## Order of work

1. `packaging_info.is_packaged()`, with tests faking both answers.
2. The visible-path translation (section 3), then Report a Problem, Open folder and the printed paths through it.
3. Hide "Unlocking warmer colors" and "Check for updates" when packaged; skip `set_app_id()`; add `RegisterApplicationRestart`.
4. StartupTask support in `autostart.py` (decide the WinRT route first), with the five states and the Windows Settings link.
5. The "other Winlight is installed" check.
6. Manifest, assets and `build.py --msix`; test-sign; the testing checklist above.
7. Partner Center listing and the first submission.

## References

- [Prepare to package a desktop application (MSIX)](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare)
- [Microsoft Store policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)
- [Flexible virtualization (AppData and registry redirection)](https://learn.microsoft.com/en-us/windows/msix/desktop/flexible-virtualization)
- [StartupTask class](https://learn.microsoft.com/en-us/uwp/api/Windows.ApplicationModel.StartupTask)
- [Code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
- [MSI/EXE submissions](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/create-app-submission)
- [Twinkle Tray's package.json (appx build)](https://github.com/xanderfrangos/twinkle-tray/blob/master/package.json) and [its execution alias](https://github.com/xanderfrangos/twinkle-tray/blob/master/resources/appx/extensions.xml)
- [Monitorian's StartupAgency (StartupTask and Run key workers)](https://github.com/emoacht/Monitorian/tree/master/Source/StartupAgency)
