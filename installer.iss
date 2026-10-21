; Установщик «Мониторинг цен» для Windows (Inno Setup 6). Собирается из build_windows.ps1 после PyInstaller.
#define AppName "Мониторинг цен"
#define AppVersion "1.0"
#define AppExe "MonitoringPrices.exe"

[Setup]
AppId={{6C1E2B6A-4F3E-4C1B-9A7E-1E7B5D2C9F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Без прав администратора — ставится для текущего пользователя; можно выбрать «для всех»
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename={#AppName} — установка
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "dist\MonitoringPrices\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Для сбора цен нужен установленный Google Chrome: Ozon и Wildberries пропускают только «настоящий» браузер
function ChromeInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') or
            RegKeyExists(HKCU, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe');
end;

// Антивирус (бывает с Kaspersky) не даёт записать библиотеки Qt — без них программа падает при запуске
function QtInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\_internal\PySide6\QtCore.pyd')) and
            FileExists(ExpandConstant('{app}\_internal\shiboken6\Shiboken.pyd'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not QtInstalled() then
    MsgBox('Не все файлы программы записались: нет библиотек Qt в папке ' + ExpandConstant('{app}\_internal') + '. '
           + 'Обычно их блокирует антивирус. Добавьте эту папку в исключения антивируса (или приостановите защиту '
           + 'на время установки) и запустите установку ещё раз.', mbError, MB_OK);
  if (CurStep = ssPostInstall) and not ChromeInstalled() then
    MsgBox('Для работы программы нужен Google Chrome — установите его с https://www.google.com/chrome/ '
           + 'перед первым запуском мониторинга.', mbInformation, MB_OK);
end;
