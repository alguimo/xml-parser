; Inno Setup installer script for Convertisseur WEDA.
; Saved as UTF-8 with BOM so French accents render across all Inno Setup versions.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Convertisseur WEDA"
#define MyAppExeName "Convertisseur WEDA.exe"
#define MyStartupValueName "ConvertisseurWEDA"

[Setup]
AppId={{8E9D5C42-3A7E-4B1F-9C28-7D4E6F1A2B3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=ConvertisseurWEDA-Setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
AppMutex=ConvertisseurWedaMutex
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#if VER >= EncodeVer(6,3,0,0)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#else
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
#endif

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Lancer automatiquement au démarrage de Windows (en arrière-plan)"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyStartupValueName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: startup; Check: IsInteractiveInstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyStartupValueName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Check: ShouldKeepStartupOnAutoUpdate

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--minimized"; Flags: nowait; Check: IsAutoUpdate

[Code]
const
  EVENT_MODIFY_STATE = $0002;
  RUN_SUBKEY = 'Software\Microsoft\Windows\CurrentVersion\Run';

function OpenEventW(dwDesiredAccess: DWORD; bInheritHandle: BOOL; lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function IsAutoUpdate(): Boolean;
var
  I: Integer;
  Arg: String;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    Arg := Uppercase(ParamStr(I));
    if (Arg = '/AUTOUPDATE') or (Arg = '/AUTOUPDATE=1') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsInteractiveInstall(): Boolean;
begin
  Result := not IsAutoUpdate();
end;

function ShouldKeepStartupOnAutoUpdate(): Boolean;
begin
  Result := IsAutoUpdate() and RegValueExists(HKEY_CURRENT_USER, RUN_SUBKEY, '{#MyStartupValueName}');
end;

procedure RequestRunningInstanceQuit(MaxTicks: Integer);
var
  EventHandle: THandle;
  I: Integer;
begin
  EventHandle := OpenEventW(EVENT_MODIFY_STATE, False, 'ConvertisseurWedaQuitEvent');
  if EventHandle <> 0 then
  begin
    SetEvent(EventHandle);
    CloseHandle(EventHandle);
  end;
  for I := 1 to MaxTicks do
  begin
    if not CheckForMutexes('ConvertisseurWedaMutex') then
      Break;
    Sleep(200);
  end;
end;

function InitializeSetup(): Boolean;
begin
  if IsAutoUpdate() then
  begin
    RequestRunningInstanceQuit(50);
    Sleep(600);
  end
  else
  begin
    RequestRunningInstanceQuit(20);
  end;
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  RequestRunningInstanceQuit(20);
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not IsAutoUpdate()) and (not WizardIsTaskSelected('startup')) then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RUN_SUBKEY, '{#MyStartupValueName}');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RUN_SUBKEY, '{#MyStartupValueName}');
  end;
end;
