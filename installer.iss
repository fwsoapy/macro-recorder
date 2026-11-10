; Macro Recorder one-click installer. Built by build.py from release\app\MacroRecorder.
; Installs for the current user only, so it needs no admin prompt, and shows no wizard pages:
; double-click it, it installs, and Macro Recorder opens.

#define AppName "Macro Recorder"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppExe "MacroRecorder.exe"

[Setup]
AppId={{5B7E9C2A-3F4D-4E8B-9A61-2C7D8E1F0A93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=fwsoapy
AppPublisherURL=https://github.com/fwsoapy/macro-recorder
AppSupportURL=https://github.com/fwsoapy/macro-recorder/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=release
OutputBaseFilename=MacroRecorderSetup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Files]
Source: "release\app\MacroRecorder\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
; With the finished page turned off this runs straight after installing, so the app just opens.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"
