#!/bin/zsh
# Установщик для Windows, собранный на Mac через Wine — когда нет ни компьютера с Windows, ни GitHub Actions.
# Те же шаги, что в build_windows.ps1 (без проверки установки: её честно делает только настоящая Windows).
#
# Первый запуск ставит всё нужное в ~/.local/share/wine-build (~1,5 ГБ): Wine, Python 3.12 для Windows, Inno Setup 6.
# Запуск из папки проекта:  APP_VERSION=1.2.0 ./build_windows_wine.sh
# Результат: dist/MonitoringPrices-Windows-Setup.exe (собирается из последнего коммита — git archive HEAD)
set -euo pipefail
cd "$(dirname "$0")"

W="$HOME/.local/share/wine-build"
WINE_VERSION=11.18
PY_VERSION=3.12.10
INNO_TAG=is-6_7_3 INNO_EXE=innosetup-6.7.3.exe
export WINEPREFIX="$W/prefix" WINEDEBUG=-all MVK_CONFIG_LOG_LEVEL=0 WINEDLLOVERRIDES="mscoree,mshtml="
export PATH="$W/Wine Devel.app/Contents/Resources/wine/bin:$PATH"
mkdir -p "$W/dl"

if ! command -v wine >/dev/null; then
  echo "== Wine $WINE_VERSION"
  curl -fsSL -o "$W/dl/wine.tar.xz" \
    "https://github.com/Gcenx/macOS_Wine_builds/releases/download/$WINE_VERSION/wine-devel-$WINE_VERSION-osx64.tar.xz"
  tar xf "$W/dl/wine.tar.xz" -C "$W"
  xattr -dr com.apple.quarantine "$W/Wine Devel.app" 2>/dev/null || true
fi
[[ -d "$WINEPREFIX/drive_c" ]] || { echo "== Префикс Wine"; wineboot -i >/dev/null 2>&1; wineserver -w; }

C="$WINEPREFIX/drive_c"
if [[ ! -f "$C/venv/Scripts/python.exe" ]]; then
  echo "== Python $PY_VERSION для Windows"
  curl -fsSL -o "$W/dl/py.nupkg" "https://www.nuget.org/api/v2/package/python/$PY_VERSION"
  rm -rf "$W/dl/pyx" && unzip -q "$W/dl/py.nupkg" 'tools/*' -d "$W/dl/pyx"
  mkdir -p "$C/py" && cp -R "$W/dl/pyx/tools/." "$C/py/"
  wine 'C:\py\python.exe' -m venv 'C:\venv'
fi
ISCC="$C/users/$USER/AppData/Local/Programs/Inno Setup 6/ISCC.exe"
if [[ ! -f "$ISCC" ]]; then
  echo "== Inno Setup 6"
  curl -fsSL -o "$W/dl/is.exe" "https://github.com/jrsoftware/issrc/releases/download/$INNO_TAG/$INNO_EXE"
  wine "$W/dl/is.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER >/dev/null 2>&1
  wineserver -w
fi

echo "== Исходники (последний коммит)"
rm -rf "$C/build" && mkdir -p "$C/build"
git archive HEAD | tar x -C "$C/build"
PY='C:\venv\Scripts\python.exe'
win() { (cd "$C/build" && wine "$@"); }
win "$PY" -m pip install -q --disable-pip-version-check -r requirements.txt pyinstaller

echo "== Иконка"
win "$PY" -c "from PIL import Image; Image.open('assets/icon.png').save('assets/app.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

HIDDEN=(--hidden-import run --hidden-import fill_links --hidden-import nosimo --hidden-import make_links_template
        --hidden-import screenshot --hidden-import excel_html --hidden-import stores --hidden-import matching
        --hidden-import excel --hidden-import config --hidden-import paths --hidden-import phone_matching
        --hidden-import phone_sites --hidden-import layout)

echo "== Программа (PyInstaller)"
win "$PY" -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name MonitoringPrices \
  --icon 'assets\app.ico' --add-data 'assets;assets' --add-data 'docs;docs' --collect-all playwright \
  "${HIDDEN[@]}" desktop_app.py

echo "== Скрипты (консольный monitoring-tools.exe)"
win "$PY" -m PyInstaller --noconfirm --clean --console --log-level WARN --name monitoring-tools \
  --distpath 'dist\tools-build' --workpath 'build\tools' --collect-all playwright \
  --exclude-module PySide6 --exclude-module tkinter "${HIDDEN[@]}" tools_main.py
rm -rf "$C/build/dist/MonitoringPrices/tools"
cp -R "$C/build/dist/tools-build/monitoring-tools" "$C/build/dist/MonitoringPrices/tools"

echo "== Проверка: скрипты отвечают, Qt на месте"
win 'dist\MonitoringPrices\tools\monitoring-tools.exe' run --help | head -1
for f in PySide6/QtCore.pyd shiboken6/Shiboken.pyd; do
  [[ -f "$C/build/dist/MonitoringPrices/_internal/$f" ]] || { echo "Нет $f в сборке"; exit 1; }
done

echo "== Установщик (Inno Setup)"
win "$ISCC" /Q ${APP_VERSION:+"/DAppVersion=$APP_VERSION"} installer.iss
mkdir -p dist
cp "$(ls "$C"/build/dist/*.exe | head -1)" dist/MonitoringPrices-Windows-Setup.exe
echo "Готово: dist/MonitoringPrices-Windows-Setup.exe ($(du -h dist/MonitoringPrices-Windows-Setup.exe | cut -f1))"
