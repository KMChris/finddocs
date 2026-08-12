; Instalator FindDocs dla Windows 11 (Inno Setup 6).
;
; Budowanie:
;   iscc packaging\finddocs.iss
; albo przez skrypt:
;   .venv\Scripts\python.exe packaging\build_installer.py
;
; Instalator dziala w trybie dla biezacego uzytkownika, wiec nie wymaga uprawnien
; administratora. Dzieki temu mozna go uruchomic na stacji roboczej z ograniczonymi
; uprawnieniami, co jest typowe w srodowisku korporacyjnym.

#define AppName "FindDocs"
#define AppVersion "0.3.0"
#define AppPublisher "Krzysztof Mizgała"
#define AppExeName "FindDocs.exe"
#define SourceDir "output\FindDocs"

[Setup]
AppId={{9A1B2C3D-4E5F-4A6B-9C8D-FD0C1E2A3B4C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Wartosc "commandline" zamiast "dialog" jest tu istotna. Przy "dialog" Inno Setup
; pyta o zakres instalacji w osobnym oknie pokazywanym jeszcze przed kreatorem,
; a tego okna nie ukrywa ani /SILENT, ani /VERYSILENT. Instalacja cicha stawala
; przez to w miejscu i czekala na klikniecie, ktorego nikt nie widzial.
; Administrator moze nadal wymusic instalacje dla wszystkich przez /ALLUSERS.
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=output
OutputBaseFilename=FindDocs-{#AppVersion}-instalator
SetupIconFile=..\src\finddocs\resources\finddocs.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "Utworz skrot na pulpicie"; \
    GroupDescription: "Skroty:"; Flags: unchecked
Name: "startmenuicon"; Description: "Utworz skrot w menu Start"; \
    GroupDescription: "Skroty:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: startmenuicon; Comment: "Lokalna wyszukiwarka dokumentow"
Name: "{group}\Dokumentacja FindDocs"; Filename: "{app}\docs"; Tasks: startmenuicon
Name: "{group}\Odinstaluj {#AppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon; Comment: "Lokalna wyszukiwarka dokumentow"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Uruchom {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Katalog danych uzytkownika (indeks, konfiguracja, logi) NIE jest usuwany
; automatycznie. Usuniecie indeksu bez pytania byloby dla uzytkownika strata
; wielogodzinnej pracy. Instalator pyta o to w kodzie ponizej.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\FindDocs');
    if DirExists(DataDir) then
    begin
      if MsgBox('Usunac takze dane aplikacji (indeks, konfiguracja, logi)?' + #13#10 +
                'Katalog: ' + DataDir + #13#10 + #13#10 +
                'Wybierz Nie, jesli planujesz ponowna instalacje i chcesz zachowac indeks.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
