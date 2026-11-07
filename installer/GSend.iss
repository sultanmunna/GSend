; Inno Setup script for GSend (optional installer, DECISIONS D-12).
; Per-user install: no admin rights, installs to %LOCALAPPDATA%\Programs.
; Build:  iscc installer\GSend.iss   (after scripts\build_exe.ps1)

#define AppName "GSend"
#define AppExe "GSend.exe"
#define AppVersion GetFileVersion("..\dist\GSend\" + AppExe)

[Setup]
AppId={{7E1A2C44-9C0B-4E1D-9A57-GSEND000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\GSend
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=GSendSetup
OutputDir=..\dist\installer
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\app.ico

[Files]
Source: "..\dist\GSend\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Hint shown to the user; token removal happens in the app (Remove account).
Filename: "{app}\{#AppExe}"; Flags: unchecked
