; SPDX-License-Identifier: GPL-3.0-only
; Inno Setup 6 script for Winlight. Built by packaging/build.py, which passes
; AppVersion, VersionNumbers, SourceDir, OutputDir and IconFile with /D.
;
; Installs for the current user only (no administrator prompt), like
; Monitorian's and Twinkle Tray's per-user installs.

#ifndef AppVersion
  #error Build with packaging/build.py
#endif

[Setup]
; Never change AppId: it is how upgrades and the uninstaller find the install.
AppId={{F658C16C-1589-4566-8E3C-295499D77F23}
AppName=Winlight
AppVersion={#AppVersion}
AppVerName=Winlight {#AppVersion}
VersionInfoVersion={#VersionNumbers}
AppPublisher=Anurag Jha
AppCopyright=Copyright (C) 2026 Anurag Jha. Free software under the GNU GPL v3.0.
VersionInfoCompany=Anurag Jha
VersionInfoDescription=Winlight setup: brightness and night light for every display
AppPublisherURL=https://github.com/Arnie14/WinLight
AppSupportURL=https://github.com/Arnie14/WinLight/issues
AppUpdatesURL=https://github.com/Arnie14/WinLight/releases
DefaultDirName={localappdata}\Programs\Winlight
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Winlight-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Winlight.exe
UninstallDisplayName=Winlight
WizardStyle=modern
; Shown before installing: a disclaimer, what clashes with Winlight, recommendations.
InfoBeforeFile=installer-notes.txt
Compression=lzma2/max
SolidCompression=yes
; Close a running copy through Windows' Restart Manager if --quit didn't.
CloseApplications=yes
RestartApplications=no
; Tell Windows about the PATH change (the optional command line task).
ChangesEnvironment=yes

[Tasks]
Name: "startup"; Description: "Start Winlight when I sign in (recommended)"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add winlight-cli to PATH, to control Winlight from scripts and the command line"; GroupDescription: "Command line:"; Flags: unchecked

[InstallDelete]
; An update replaces the app's runtime folder rather than adding to it: files
; an older version shipped and this one doesn't (a former Python's DLLs, say)
; would stay, and could be loaded in place of Windows' own. Nothing of the
; user's is in it: settings live in %LOCALAPPDATA%\WinLight.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; The app folder, with LICENSE.txt and THIRD_PARTY_NOTICES.txt (packaging/build.py puts them there).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Winlight"; Filename: "{app}\Winlight.exe"; AppUserModelID: "Winlight.Winlight"
Name: "{autodesktop}\Winlight"; Filename: "{app}\Winlight.exe"; AppUserModelID: "Winlight.Winlight"; Tasks: desktopicon

[Registry]
; Starting at sign-in. The installer writes this value, not the app: an
; unsigned program adding itself to the Run key looks like malware setting
; itself up to persist to Microsoft Defender (Behavior:Win32/Persistence.A!ml).
; The app's setting only switches it on and off, as Task Manager does.
; An update writes it only where it still is (see KeepStartupEntry).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Winlight"; ValueData: """{app}\Winlight.exe"""; Flags: uninsdeletevalue; Tasks: startup; Check: KeepStartupEntry
; The user's own PATH, so no administrator rights are needed; removed again on uninstall.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NotOnPath(ExpandConstant('{app}'))

[Run]
; Started only if ticked on the last page, and after any other copy quits.
Filename: "{app}\Winlight.exe"; Description: "{cm:LaunchProgram,Winlight}"; Flags: nowait postinstall skipifsilent; BeforeInstall: QuitAnyOtherCopy

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  ApprovedKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';
  EnvKey = 'Environment';

function NotOnPath(Dir: String): Boolean;
var
  Path: String;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path) then
    Path := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';') = 0;
end;

procedure RemoveFromPath(Dir: String);
var
  Path: String;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path) then
    exit;
  P := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Path) + ';');
  if P = 0 then
    exit;
  { In ';' + Path + ';' the match starts at the separator before the entry,
    so in Path the entry starts at P. Remove it with one separator: the one
    before it, or after it when it is the first entry. }
  if P = 1 then
    Delete(Path, 1, Length(Dir) + 1)
  else
    Delete(Path, P - 1, Length(Dir) + 1);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', Path);
end;

{ Ask a running Winlight to quit, so it puts the screen colors back to
  normal before its files are replaced or removed. Killing it instead would
  leave the night light tint on screen until the next restart. }
procedure QuitRunningCopy(const Exe: String);
var
  ResultCode: Integer;
begin
  if FileExists(Exe) then
  begin
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1500);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunningCopy(ExpandConstant('{app}\Winlight.exe'));
  Result := '';
end;

{ Before the new copy starts: a copy running from elsewhere (the portable
  zip) would otherwise keep running, and the new one, finding it, would only
  open its panel and exit. --quit reaches whichever copy is running, as
  copies are one per user, wherever they are. }
procedure QuitAnyOtherCopy();
begin
  QuitRunningCopy(ExpandConstant('{app}\Winlight.exe'));
end;

{ --- Saying it's an update ---------------------------------------------------
  Run again over an installed Winlight, Setup updates it in place (AppId):
  the same folder, one entry in Installed apps, settings kept. Its pages
  looked like a first install's, which read as making a second copy. }

const
  { Where Setup recorded the install: AppId and "_is1", for this user only. }
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{F658C16C-1589-4566-8E3C-295499D77F23}_is1';

var
  InstalledVersion: String;  { '' on a first install }

function InitializeSetup(): Boolean;
begin
  if not RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', InstalledVersion) then
    InstalledVersion := '';
  Result := True;
end;

{ "0.8.0-beta.2" -> "0.8.0 Beta 2", as the app and its releases write it. }
function ShownVersion(Version: String): String;
var
  P: Integer;
  Pre: String;
begin
  P := Pos('-', Version);
  if P = 0 then
  begin
    Result := Version;
    exit;
  end;
  Pre := Copy(Version, P + 1, Length(Version));
  StringChangeEx(Pre, '.', ' ', True);
  Result := Copy(Version, 1, P - 1) + ' ' + Uppercase(Copy(Pre, 1, 1)) + Copy(Pre, 2, Length(Pre));
end;

function UpdateText(): String;
begin
  if InstalledVersion = '{#AppVersion}' then
    Result := 'Winlight ' + ShownVersion(InstalledVersion) + ' is installed already. Setup installs it again and keeps your settings.'
  else
    Result := 'Winlight ' + ShownVersion(InstalledVersion) + ' is installed. Setup updates it to ' +
      ShownVersion('{#AppVersion}') + ' and keeps your settings.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if InstalledVersion = '' then
    exit;
  case CurPageID of
    wpInfoBefore:
      WizardForm.PageDescriptionLabel.Caption := UpdateText();
    wpReady:
      begin
        WizardForm.PageNameLabel.Caption := 'Ready to update';
        WizardForm.PageDescriptionLabel.Caption := UpdateText();
        WizardForm.ReadyLabel.Caption := 'Click Update to continue. Winlight closes first and puts the screen''s colors back.';
        WizardForm.NextButton.Caption := 'Update';
      end;
    wpFinished:
      if InstalledVersion = '{#AppVersion}' then
        WizardForm.FinishedLabel.Caption := 'Winlight ' + ShownVersion('{#AppVersion}') +
          ' is installed again. Your settings are as you left them.'
      else
        WizardForm.FinishedLabel.Caption := 'Winlight is updated to ' + ShownVersion('{#AppVersion}') +
          '. Your settings are as you left them.';
  end;
end;

{ Whether to write the start-at-sign-in entry. A first install: the task
  decides. An update: the entry is written again where it still is, but one
  removed since (with Autoruns, say) while the task stayed ticked isn't
  brought back, as f.lux's installer does at every update. Ticking the task
  now, where it wasn't ticked last time, still adds it. Turning it off in
  Settings or Task Manager keeps the entry (only its switch changes), so that
  choice is kept either way. }
function KeepStartupEntry(): Boolean;
var
  Previous: String;
begin
  Result := True;
  if (InstalledVersion = '') or RegValueExists(HKEY_CURRENT_USER, RunKey, 'Winlight') then
    exit;
  if RegQueryStringValue(HKCU, UninstallKey, 'Inno Setup: Selected Tasks', Previous) and
     (Pos(',startup,', ',' + Lowercase(Previous) + ',') > 0) then
    Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Unticked on an upgrade: an earlier install's (or version's) entry goes. }
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('startup') then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Winlight');
    RegDeleteValue(HKEY_CURRENT_USER, ApprovedKey, 'Winlight');
  end;
end;

const
  IcmKey = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ICM';
  GammaRangeValue = 'GdiIcmGammaRange';

var
  DeleteSettings: Boolean;
  LockColorLimit: Boolean;

{ Whether Windows' color limit is unlocked (GdiIcmGammaRange = 256), as
  Winlight's "Unlock" in Settings, f.lux and LightBulb set it. }
function ColorLimitUnlocked(): Boolean;
var
  Value: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, IcmKey, GammaRangeValue, Value) and (Value = 256);
end;

{ Asked first, before anything is removed. An uninstall is a full uninstall,
  so deleting is the default, also when uninstalling silently (winget,
  scripts; with /SUPPRESSMSGBOXES the default answer is taken). Upgrades
  install over the old version without uninstalling, so they keep settings. }
function InitializeUninstall(): Boolean;
begin
  DeleteSettings := True;
  if not UninstallSilent then
    DeleteSettings := MsgBox('Also delete your Winlight settings?' + #13#10#13#10 +
      'Winlight doesn''t leave anything behind: uninstalling it is a full uninstall, so your settings, ' +
      'logs and saved reports (in ' + ExpandConstant('{localappdata}') + '\WinLight) are deleted too.' + #13#10#13#10 +
      'If you reinstall Winlight later, it starts with default settings: deleted settings can''t be brought back.' + #13#10#13#10 +
      'Choose No to keep them for reinstalling.',
      mbConfirmation, MB_YESNO) = IDYES;
  { Windows' color limit is machine-wide and may be another app's too, so
    it's only offered, No by default, and never changed silently (it needs
    Windows' administrator prompt anyway). }
  LockColorLimit := False;
  if not UninstallSilent and ColorLimitUnlocked() then
    LockColorLimit := MsgBox('Put Windows'' color limit back?' + #13#10#13#10 +
      'Windows'' limit on how far apps can change screen colors is unlocked on this PC (the GdiIcmGammaRange ' +
      'setting), so night light can go warmer than Windows allows by default. Winlight''s "Unlock" in Settings ' +
      'sets it, and so do f.lux and LightBulb.' + #13#10#13#10 +
      'Choose Yes to put the limit back: Windows asks for administrator approval, and applies it after you sign out. ' +
      'Choose No if you use f.lux, LightBulb or another night light app: with the limit back, they stop short of ' +
      'their warmest colors too.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure LockColorLimitAgain();
var
  ResultCode: Integer;
begin
  if not ShellExec('runas', ExpandConstant('{sys}\reg.exe'),
      'delete "HKLM\' + IcmKey + '" /v ' + GammaRangeValue + ' /f', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Windows'' color limit: the administrator prompt was declined or failed; left unlocked')
  else
    Log(Format('Windows'' color limit: reg.exe ended with %d', [ResultCode]));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    QuitRunningCopy(ExpandConstant('{app}\Winlight.exe'));
  { Don't leave a start-up entry pointing at a deleted program, nor its
    on/off switch (the app may have written both, for the portable zip or
    an older version). }
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Winlight');
    RegDeleteValue(HKEY_CURRENT_USER, ApprovedKey, 'Winlight');
    RemoveFromPath(ExpandConstant('{app}'));
    if LockColorLimit then
      LockColorLimitAgain();
    if DeleteSettings then
    begin
      { The data folder, and its name before 0.3.0 if an old version left it. }
      DelTree(ExpandConstant('{localappdata}\WinLight'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\night-light'), True, True, True);
    end;
  end;
end;
