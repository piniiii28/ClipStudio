; La version la pasa compilar_escritorio.py con /DVersion=X.Y.Z (ver clipstudio/__init__.py).
#ifndef Version
  #define Version "0.1.0"
#endif

[Setup]
AppId={{40D59A85-5746-4620-A1B7-E7EA7D061C36}
AppName=ClipStudio
AppVersion={#Version}
DefaultDirName={localappdata}\Programs\ClipStudio
DefaultGroupName=ClipStudio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=ClipStudio-Setup
SetupIconFile=..\build\assets\clipstudio.ico
UninstallDisplayIcon={app}\ClipStudio.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
; Las actualizaciones desde la app usan /SILENT /CLOSEAPPLICATIONS: cierra ClipStudio si sigue abierto
; y el [Run] con skipifnotsilent lo vuelve a abrir al terminar.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\dist\ClipStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ClipStudio"; Filename: "{app}\ClipStudio.exe"
Name: "{autodesktop}\ClipStudio"; Filename: "{app}\ClipStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ClipStudio.exe"; Description: "Abrir ClipStudio"; Flags: nowait postinstall skipifsilent
Filename: "{app}\ClipStudio.exe"; Flags: nowait runasoriginaluser skipifnotsilent

; Los proyectos se guardan fuera de {app}; desinstalar conserva los datos.
