; geas.iss - Instalador de Geas (Inno Setup 6). Lo compila build_windows.py después de PyInstaller.
; Se instala para el usuario actual (sin pedir permisos de administrador), en
; %LOCALAPPDATA%\Programs\Geas, y registra el host nativo para Chrome, Edge, Chromium (y Brave, Opera, Vivaldi) y Firefox.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Geas Download Manager"
#define SourceDir "..\dist\Geas"

[Setup]
; AppId fijo: identifica a Geas en cada actualización (no cambiarlo)
AppId={{63AED91F-B2E9-4F58-9E5B-C1466195DD39}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Geas
DefaultDirName={localappdata}\Programs\Geas
DefaultGroupName=Geas
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Geas-Setup-{#AppVersion}
SetupIconFile=..\branding\geas.ico
UninstallDisplayIcon={app}\Geas.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Si Geas está abierta, el instalador la cierra (en las actualizaciones automáticas ya se cerró sola)
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Bibliotecas de la versión anterior: que no queden mezcladas con las nuevas
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; ffmpeg lo descarga Geas la primera vez (no viene en el instalador): se borra al desinstalar
Type: filesandordirs; Name: "{app}\ffmpeg"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Geas"; Filename: "{app}\Geas.exe"
Name: "{autodesktop}\Geas"; Filename: "{app}\Geas.exe"; Tasks: desktopicon

[Registry]
; Host de Native Messaging: con él la extensión entrega las descargas a Geas
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.geas.host"; ValueType: string; ValueName: ""; ValueData: "{app}\com.geas.host.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.geas.host"; ValueType: string; ValueName: ""; ValueData: "{app}\com.geas.host.json"; Flags: uninsdeletekey
; Brave, Opera y Vivaldi usan la clave de Chrome; Chromium sin marca, la suya
Root: HKCU; Subkey: "Software\Chromium\NativeMessagingHosts\com.geas.host"; ValueType: string; ValueName: ""; ValueData: "{app}\com.geas.host.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\com.geas.host"; ValueType: string; ValueName: ""; ValueData: "{app}\com.geas.host.firefox.json"; Flags: uninsdeletekey
; Cuando la extensión esté en las tiendas, Chrome y Edge la ofrecen solos al abrirse, como IDM:
; "Se agregó Geas" -> Activar. Reemplazar <ID> por el de cada tienda y quitar el punto y coma
; (y poner sus páginas en STORE_URLS de browsers.py):
; Root: HKCU; Subkey: "Software\Google\Chrome\Extensions\<ID>"; ValueType: string; ValueName: "update_url"; ValueData: "https://clients2.google.com/service/update2/crx"; Flags: uninsdeletekey
; Root: HKCU; Subkey: "Software\Microsoft\Edge\Extensions\<ID>"; ValueType: string; ValueName: "update_url"; ValueData: "https://edge.microsoft.com/extensionwebstorebase/v1/crx"; Flags: uninsdeletekey

[Run]
Filename: "{app}\Geas.exe"; Description: "{cm:LaunchProgram,Geas}"; Flags: nowait postinstall skipifsilent
; Actualización automática (instalación silenciosa): Geas vuelve a abrirse y sigue con sus descargas
Filename: "{app}\Geas.exe"; Flags: nowait; Check: WizardSilent
