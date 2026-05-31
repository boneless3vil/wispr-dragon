; Inno Setup script for the Wispr Dragon Windows client.
;
; Wraps the PyInstaller onedir output (dist\WisprDragonClient\) into a
; double-click installer with a Start-Menu shortcut and an uninstaller.
; Per-user install (no admin), so it lands in the user's Programs folder.
;
; Build the PyInstaller bundle first (see packaging/README.md), then compile:
;   ISCC.exe /DSourceDir="C:\Users\<you>\wd_build\dist\WisprDragonClient" packaging\wispr_dragon_client.iss
; The default SourceDir below is a neutral placeholder; the README builds to
; $HOME\wd_build, so always pass /DSourceDir to match your actual bundle path.

#define MyAppName "Wispr Dragon Client"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Jonathan Baldwin"
#define MyAppExeName "WisprDragonClient.exe"

; Override at compile time with /DSourceDir=...; default is a neutral placeholder.
#ifndef SourceDir
  #define SourceDir "C:\wd_build\dist\WisprDragonClient"
#endif

[Setup]
; Stable AppId so upgrades replace rather than stack. Do not reuse for other apps.
AppId={{8F2A6C41-3B7D-4E1A-9C58-2D0F7A4B6E93}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\WisprDragon
DefaultGroupName=Wispr Dragon
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=WisprDragonClient-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install — no UAC elevation required.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
