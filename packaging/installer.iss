; Inno Setup 6 telepítőszkript – WebKép Konverter
; Fordítás (a projekt gyökeréből, a PyInstaller build után):
;   iscc /DAppVersion=1.0.0 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "WebKép Konverter"
#define AppExe "WebKepKonverter.exe"
#define AppPublisher "WebKep"
#define AppURL "https://github.com/VargaFerencINF/imageconverter"

[Setup]
AppId={{6C1F4E0B-5B7A-4B8E-9E2D-7A1C3F0D9B21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\WebKep Konverter
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Rendszergazdai jog nélkül is telepíthető (felhasználói telepítés), de választható a gépszintű is.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\installer_output
OutputBaseFilename=WebKepKonverter-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}

; A magyar nyelvi fájl az Inno Setup része; ha mégis hiányozna, angol telepítő készül.
#if FileExists(AddBackslash(CompilerPath) + "Languages\Hungarian.isl")
  #define HasHungarian
#endif

[Languages]
#ifdef HasHungarian
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
#ifdef HasHungarian
hungarian.ContextMenu=Jobb klikkes menü mappákhoz: „Konvertálás a WebKép Konverterrel”
hungarian.ContextMenuLabel=Konvertálás a WebKép Konverterrel
hungarian.Integration=Windows integráció:
#endif
english.ContextMenu=Folder context menu: “Convert with WebKép Konverter”
english.ContextMenuLabel=Convert with WebKép Konverter
english.Integration=Windows integration:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "contextmenu"; Description: "{cm:ContextMenu}"; GroupDescription: "{cm:Integration}"

[Files]
Source: "..\dist\WebKepKonverter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\webkep-cli.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme skipifsourcedoesntexist
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Jobb klikk egy mappán, illetve egy mappa hátterén az Intézőben
Root: HKCU; Subkey: "Software\Classes\Directory\shell\WebKepKonverter"; ValueType: string; ValueName: ""; ValueData: "{cm:ContextMenuLabel}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\WebKepKonverter"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\WebKepKonverter\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\WebKepKonverter"; ValueType: string; ValueName: ""; ValueData: "{cm:ContextMenuLabel}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\WebKepKonverter"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\WebKepKonverter\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
