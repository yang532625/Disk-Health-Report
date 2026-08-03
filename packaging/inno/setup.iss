; Disk Health Report — Inno Setup installer (primary distribution)
; Customize branding in config.iss.inc | version in version.py

#include "config.iss.inc"
#include "version.iss.inc"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppSupportURL}
AppUpdatesURL={#MyAppUpdatesURL}
DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppGroupName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
OutputDir={#MySetupOutputDir}
OutputBaseFilename={#MySetupBaseName}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
LicenseFile=..\assets\LICENSE_smartmontools.txt
InfoBeforeFile=info-before.txt
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
WizardSizePercent=120
PrivilegesRequired={#MyPrivileges}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion={#MyMinWindows}
; --- In-place upgrades (same AppId → sobrescribe, no instalación paralela) ---
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
UsePreviousLanguage=yes
CloseApplications=force
RestartApplications=no
AppMutex={#MyAppMutex}
DisableWelcomePage=no
; No dejar elegir otra carpeta: siempre la instalación existente / Program Files
DisableDirPage=yes
DisableFinishedPage=no
ShowLanguageDialog=auto
DirExistsWarning=no
; Version metadata (Add/Remove Programs + file properties)
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (C) {#MyAppPublisher}
; Stronger UX
SetupLogging=yes
RestartIfNeededByRun=no
; Runtime cache lives under %LOCALAPPDATA% (intentional; cleaned on uninstall)
UsedUserAreasWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Types]
Name: "full"; Description: "Full installation / Instalacion completa"
Name: "compact"; Description: "Compact (app only) / Compacta (solo app)"
Name: "custom"; Description: "Custom / Personalizada"; Flags: iscustom

[Components]
Name: "main"; Description: "Disk Health Report application"; Types: full compact custom; Flags: fixed
Name: "samples"; Description: "Sample SMART dumps (for offline demos)"; Types: full custom
Name: "shortcuts"; Description: "Start Menu shortcuts"; Types: full compact custom

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Components: shortcuts; Flags: checkedonce
Name: "startup"; Description: "Launch at Windows startup / Iniciar con Windows"; GroupDescription: "Startup / Inicio"; Flags: unchecked

[Files]
; Main application (PyInstaller single-file)
Source: "{#MyAppBinary}"; DestDir: "{app}"; Flags: ignoreversion; Components: main
; Optional samples
Source: "..\..\samples\*"; DestDir: "{app}\samples"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: samples

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Components: shortcuts
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; Components: shortcuts
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Registry]
; Optional Run-at-startup (machine — installer requires admin)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppNameShort}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup
; App identity for future auto-updaters
Root: HKLM; Subkey: "Software\{#MyAppPublisher}\{#MyAppNameShort}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\{#MyAppPublisher}\{#MyAppNameShort}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

[Run]
; Wizard installs: optional launch checkbox on finish page
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent shellexec
; Silent in-app updates: relaunch automatically after upgrade
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifnotsilent shellexec

[UninstallDelete]
; Runtime extracts (smartctl cache etc.) — keep user reports + settings in APPDATA
Type: filesandordirs; Name: "{localappdata}\{#MyAppNameShort}\runtime"
Type: files; Name: "{app}\*.log"
; Nunca borrar %APPDATA%\DiskHealthReport\settings.json (carpeta de reportes / idioma)

[Messages]
english.WelcomeLabel1=Welcome to [name] Setup
english.FinishedLabel=Setup has finished installing [name] on your computer.%n%nReports are saved under Documents\{#MyReportsFolder}\
spanish.WelcomeLabel1=Bienvenido al instalador de [name]
spanish.FinishedLabel=La instalacion de [name] ha finalizado.%n%nLos reportes se guardan en Documentos\{#MyReportsFolder}\

[Code]
const
  UninstallRegKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';

var
  IsUpdateInstall: Boolean;
  PreviousVersion: String;

function GetInstalledVersion(): String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, UninstallRegKey, 'DisplayVersion', Result) then
    Exit;
  if RegQueryStringValue(HKCU, UninstallRegKey, 'DisplayVersion', Result) then
    Exit;
  if RegQueryStringValue(HKLM, 'Software\{#MyAppPublisher}\{#MyAppNameShort}', 'Version', Result) then
    Exit;
end;

function InitializeSetup(): Boolean;
var
  ExistingExe: String;
begin
  IsUpdateInstall := False;
  PreviousVersion := GetInstalledVersion();
  if PreviousVersion <> '' then
    IsUpdateInstall := True
  else
  begin
    { Sin clave de desinstalación: si el EXE ya está en Program Files, es actualización. }
    ExistingExe := ExpandConstant('{autopf}\{#MyAppDirName}\{#MyAppExeName}');
    if FileExists(ExistingExe) then
      IsUpdateInstall := True;
  end;
  Result := True;
end;

procedure InitializeWizard();
var
  Msg: String;
begin
  if IsUpdateInstall then
  begin
    WizardForm.Caption := ExpandConstant('{#MyAppName}') + ' — Update';
    if ActiveLanguage = 'spanish' then
    begin
      WizardForm.Caption := ExpandConstant('{#MyAppName}') + ' — Actualizacion';
      Msg := 'Se detecto una instalacion previa (v' + PreviousVersion + ').' + #13#10 +
             'Se instalara la version {#MyAppVersion} sobre la existente.' + #13#10 + #13#10 +
             'Se conservan: reportes en Documentos y preferencias del usuario.' + #13#10 +
             'Se actualizan: el ejecutable y componentes del programa.';
    end
    else
      Msg := 'A previous installation was detected (v' + PreviousVersion + ').' + #13#10 +
             'Version {#MyAppVersion} will be installed in place.' + #13#10 + #13#10 +
             'Preserved: reports in Documents and user settings.' + #13#10 +
             'Updated: application binary and program components.';
    WizardForm.WelcomeLabel2.Caption := Msg;
  end
  else
  begin
    if ActiveLanguage = 'spanish' then
      WizardForm.WelcomeLabel2.Caption :=
        'Esto instalara [name/ver] en su equipo.' + #13#10 + #13#10 +
        'Incluye motor S.M.A.R.T., vista previa de reportes y herramientas de disco.' + #13#10 +
        'No necesita Python ni instalaciones adicionales.' + #13#10 + #13#10 +
        'Se recomienda cerrar otras aplicaciones antes de continuar.'
    else
      WizardForm.WelcomeLabel2.Caption :=
        'This will install [name/ver] on your computer.' + #13#10 + #13#10 +
        'Includes S.M.A.R.T. engine, report preview and disk tools.' + #13#10 +
        'No Python or extra installs required.' + #13#10 + #13#10 +
        'It is recommended that you close other applications before continuing.';
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  NeedsRestart := False;
  if IsUpdateInstall then
  begin
    if ActiveLanguage = 'spanish' then
      WizardForm.StatusLabel.Caption := 'Actualizando {#MyAppName}...'
    else
      WizardForm.StatusLabel.Caption := 'Updating {#MyAppName}...';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and IsUpdateInstall then
  begin
    if ActiveLanguage = 'spanish' then
      WizardForm.StatusLabel.Caption := 'Actualizacion completada — v{#MyAppVersion}'
    else
      WizardForm.StatusLabel.Caption := 'Update completed — v{#MyAppVersion}';
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
end;
