#ifndef Payload
  #error "Use installer/build.ps1 to assemble the payload."
#endif

[Setup]
AppId=Druttzen.TF3MapStudio
AppName=TF3 Map Studio
AppVersion=0.1
AppPublisher=Druttzen
AppPublisherURL=https://github.com/Druttzen/TF3-Map-Studio
DefaultDirName={localappdata}\Programs\TF3 Map Studio
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=TF3-Map-Studio-Setup
Compression=lzma2/fast
SolidCompression=yes
SetupMutex=Druttzen.TF3MapStudio.Setup
CloseApplications=no

[Files]
Source: "{#Payload}\setup-game.exe"; Flags: dontcopy
Source: "{#Payload}\importer.zip"; Flags: dontcopy
Source: "{#Payload}\OSM-TF3-Vanilla-Converter\*"; DestDir: "{app}\OSM-TF3-Vanilla-Converter"; Flags: ignoreversion
Source: "{#Payload}\TF3-Heightmap-Studio\*"; DestDir: "{app}\TF3-Heightmap-Studio"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\TF3 Map Studio\OSM Converter"; Filename: "{app}\OSM-TF3-Vanilla-Converter\OSM-TF3-Vanilla-Converter.exe"; WorkingDir: "{app}\OSM-TF3-Vanilla-Converter"
Name: "{userprograms}\TF3 Map Studio\Heightmap Studio"; Filename: "{app}\TF3-Heightmap-Studio\TF3-Heightmap-Studio.exe"; WorkingDir: "{app}\TF3-Heightmap-Studio"

[Registry]
Root: HKCU; Subkey: "Software\TF3 Map Studio\Heightmap Studio"; ValueType: string; ValueName: "Installation"; ValueData: "{code:SelectedPath|0}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\TF3 Map Studio\Heightmap Studio"; ValueType: string; ValueName: "UserData"; ValueData: "{code:SelectedPath|1}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\TF3 Map Studio\Heightmap Studio"; ValueType: string; ValueName: "Importer"; ValueData: "{code:SelectedPath|2}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\TF3 Map Studio\OSM Converter"; ValueType: string; ValueName: "Importer"; ValueData: "{code:SelectedPath|2}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Code]
var
  PathsPage: TInputQueryWizardPage;
  InstalledPaths: TArrayOfString;

function RunHelper(Mode, Extra: String; var Lines: TArrayOfString): Boolean;
var
  ExitCode: Integer;
  OutputFile: String;
begin
  OutputFile := ExpandConstant('{tmp}\tf3-paths.txt');
  DeleteFile(OutputFile);
  Result := Exec(ExpandConstant('{tmp}\setup-game.exe'),
    Mode + ' ' + AddQuotes(OutputFile) + Extra, ExpandConstant('{tmp}'),
    SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then
  begin
    Result := LoadStringsFromFile(OutputFile, Lines);
    if Result and (GetArrayLength(Lines) > 0) then
      Result := (ExitCode = 0) and (Lines[0] = 'OK')
    else
      Result := False;
  end;
end;

procedure BrowseTF3Folder(Sender: TObject);
var
  Index: Integer;
  Folder: String;
begin
  Index := TNewButton(Sender).Tag;
  Folder := PathsPage.Values[Index];
  if BrowseForFolder(PathsPage.PromptLabels[Index].Caption, Folder, False) then
    PathsPage.Values[Index] := Folder;
end;

procedure AddFolderField(Prompt: String);
var
  Index: Integer;
  Browse: TNewButton;
begin
  Index := PathsPage.Add(Prompt, False);
  PathsPage.Edits[Index].Width := PathsPage.Edits[Index].Width - ScaleX(88);
  Browse := TNewButton.Create(PathsPage);
  Browse.Parent := PathsPage.Surface;
  Browse.Caption := 'Browse...';
  Browse.Left := PathsPage.Edits[Index].Left + PathsPage.Edits[Index].Width + ScaleX(8);
  Browse.Top := PathsPage.Edits[Index].Top - 1;
  Browse.Width := ScaleX(80);
  Browse.Height := WizardForm.NextButton.Height;
  Browse.Tag := Index;
  Browse.OnClick := @BrowseTF3Folder;
end;

procedure InitializeWizard;
var
  Detected: TArrayOfString;
  Existing: String;
begin
  { The standard directory page rejects empty fields even in silent mode. }
  PathsPage := CreateInputQueryPage(wpSelectDir, 'Transport Fever 3 folders',
    'Choose the game and the user profile for your maps.',
    'Setup puts the OSM Importer mod in the selected user folder. ' +
    'Leave the user folder blank to install only the desktop apps. ' +
    'You can find the user folder in TF3 under Settings > Advanced > Open User Data Folder.');
  AddFolderField('Game installation folder:');
  AddFolderField('User data folder:');
  ExtractTemporaryFile('setup-game.exe');
  if RunHelper('detect', '', Detected) and (GetArrayLength(Detected) >= 3) then
  begin
    PathsPage.Values[0] := Detected[1];
    PathsPage.Values[1] := Detected[2];
    if (Detected[2] = '') and (GetArrayLength(Detected) > 3) then
    begin
      PathsPage.Edits[1].ShowHint := True;
      PathsPage.Edits[1].Hint := 'Detected profile: ' + Detected[3];
    end;
  end;
  if RegQueryStringValue(HKCU, 'Software\TF3 Map Studio\Heightmap Studio', 'Installation', Existing)
    and FileExists(AddBackslash(Existing) + 'TransportFever3.exe') then
    PathsPage.Values[0] := Existing;
  if RegQueryStringValue(HKCU, 'Software\TF3 Map Studio\Heightmap Studio', 'UserData', Existing)
    and DirExists(Existing) then
    PathsPage.Values[1] := Existing;
  Existing := ExpandConstant('{param:TF3GAME|<auto>}');
  if Existing <> '<auto>' then PathsPage.Values[0] := Existing;
  Existing := ExpandConstant('{param:TF3USER|<auto>}');
  if Existing <> '<auto>' then PathsPage.Values[1] := Existing;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Choices: TArrayOfString;
  ChoiceFile: String;
begin
  SetArrayLength(Choices, 3);
  Choices[0] := Trim(PathsPage.Values[0]);
  Choices[1] := Trim(PathsPage.Values[1]);
  Choices[2] := WizardDirValue;
  ChoiceFile := ExpandConstant('{tmp}\tf3-selection.txt');
  Result := 'Setup could not prepare the Transport Fever 3 folders.';
  if not SaveStringsToUTF8File(ChoiceFile, Choices, False) then Exit;
  if not FileExists(ExpandConstant('{tmp}\importer.zip')) then
    ExtractTemporaryFile('importer.zip');
  if RunHelper('install', ' ' + AddQuotes(ChoiceFile) + ' ' +
    AddQuotes(ExpandConstant('{tmp}\importer.zip')), InstalledPaths) then
    Result := ''
  else if GetArrayLength(InstalledPaths) >= 2 then
    Result := InstalledPaths[1];
end;

function SelectedPath(Index: String): String;
var
  Line: Integer;
begin
  Line := StrToInt(Index) + 1;
  Result := '';
  if Line < GetArrayLength(InstalledPaths) then
    Result := InstalledPaths[Line];
end;
