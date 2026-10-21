# Сборка «Мониторинг цен» для Windows: программа (PyInstaller) + установщик (Inno Setup).
#
# Нужно на машине сборки: Python 3.12 (python.org, галочка «Add to PATH») и Inno Setup 6 (jrsoftware.org).
# Запуск в PowerShell из папки проекта:
#     powershell -ExecutionPolicy Bypass -File build_windows.ps1
# Результат: dist\Мониторинг цен — установка.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Окружение"
if (-not (Test-Path .venv-win)) { python -m venv .venv-win }
$py = ".\.venv-win\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt pyinstaller

Write-Host "== Иконка"
& $py -c "from PIL import Image; Image.open('assets/icon.png').save('assets/app.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "== Программа (PyInstaller)"
& $py -m PyInstaller --noconfirm --clean --windowed `
    --name MonitoringPrices `
    --icon assets\app.ico `
    --add-data "assets;assets" `
    --add-data "docs;docs" `
    --collect-all playwright `
    --hidden-import run --hidden-import fill_links --hidden-import nosimo `
    --hidden-import make_links_template --hidden-import screenshot --hidden-import excel_html `
    --hidden-import stores --hidden-import matching --hidden-import excel --hidden-import config --hidden-import paths --hidden-import phone_matching --hidden-import phone_sites `
    desktop_app.py

Write-Host "== Скрипты (консольный monitoring-tools.exe)"
& $py -m PyInstaller --noconfirm --clean --console `
    --name monitoring-tools --distpath dist\tools-build --workpath build\tools `
    --collect-all playwright --exclude-module PySide6 --exclude-module tkinter `
    --hidden-import run --hidden-import fill_links --hidden-import nosimo `
    --hidden-import make_links_template --hidden-import screenshot --hidden-import excel_html `
    --hidden-import stores --hidden-import matching --hidden-import excel --hidden-import config --hidden-import paths --hidden-import phone_matching --hidden-import phone_sites `
    tools_main.py
if (Test-Path dist\MonitoringPrices\tools) { Remove-Item -Recurse -Force dist\MonitoringPrices\tools }
Copy-Item -Recurse dist\tools-build\monitoring-tools dist\MonitoringPrices\tools

Write-Host "== Проверка: скрипты отвечают"
& dist\MonitoringPrices\tools\monitoring-tools.exe run --help | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw "monitoring-tools.exe не запускается" }

Write-Host "== Установщик (Inno Setup)"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Не найден Inno Setup 6 (ISCC.exe). Установите с https://jrsoftware.org/isdl.php" }
& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup: ошибка сборки установщика" }

if ($env:CI) {
    # Только на машине сборки GitHub: ставим программу как пользователь (путь с кириллицей) и проверяем запуск Qt
    Write-Host "== Проверка: установка и запуск"
    $dir = "$env:ProgramFiles\Мониторинг цен — проверка"
    $setup = Get-ChildItem dist\*установка.exe | Select-Object -First 1
    Start-Process $setup.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$dir`"" -Wait
    # при падении PyInstaller показывает окно с ошибкой и ждёт — поэтому ожидание с таймаутом
    $p = Start-Process "$dir\MonitoringPrices.exe" -ArgumentList "--selftest" -PassThru
    if (-not $p.WaitForExit(90000)) { $p.Kill(); throw "Установленная программа не запускается (окно ошибки, таймаут)" }
    if ($p.ExitCode -ne 0) { throw "Установленная программа не запускается (код $($p.ExitCode))" }
    Write-Host "Установленная программа запускается"
}

Write-Host "Готово: dist\Мониторинг цен — установка.exe"
