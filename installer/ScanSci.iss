; ScanSci per-user Windows installer.
; Values are intentionally supplied by scripts/build_windows_installer.ps1 so
; that every installer manifest can be tied to the exact packaged desktop build.

#ifndef SourceDir
  #error SourceDir must point to the packaged ScanSci directory.
#endif

#ifndef OutputDir
  #error OutputDir must be supplied by the release build script.
#endif

#ifndef AppVersion
  #error AppVersion must be supplied by the release build script.
#endif

#ifndef UpdateManifestUrl
  #define UpdateManifestUrl ""
#endif

[Setup]
AppId={{F1A9C2B3-83AA-4B8B-89D4-68046D71D441}
AppName=ScanSci
AppVersion={#AppVersion}
AppPublisher=ScanSci
DefaultDirName={localappdata}\Programs\ScanSci
DefaultGroupName=ScanSci
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=ScanSci-{#AppVersion}-windows-x64-setup
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ScanSci.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ScanSci"; Filename: "{app}\ScanSci.exe"; Parameters: "--update-manifest-url ""{#UpdateManifestUrl}"""; WorkingDir: "{app}"
Name: "{autodesktop}\ScanSci"; Filename: "{app}\ScanSci.exe"; Parameters: "--update-manifest-url ""{#UpdateManifestUrl}"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ScanSci.exe"; Parameters: "--update-manifest-url ""{#UpdateManifestUrl}"""; Description: "Launch ScanSci"; Flags: nowait postinstall skipifsilent
