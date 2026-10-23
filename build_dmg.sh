#!/bin/zsh
# Самостоятельный установщик для Mac: «Мониторинг цен.app» со встроенным Python и скриптами → .dmg.
# Запуск из папки проекта: ./build_dmg.sh   Результат: dist/Мониторинг цен.dmg
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Мониторинг цен"
STAGE="dist/mac.noindex"  # *.noindex — заготовка образа не попадает в Spotlight
APP="$STAGE/$APP_NAME.app"
PY=${PYTHON:-.venv/bin/python}

echo "== Скрипты (PyInstaller)"
rm -rf build/tools dist/tools
$PY -m PyInstaller --noconfirm --clean --log-level WARN \
  --name monitoring-tools --distpath dist/tools --workpath build/tools --specpath build \
  --collect-all playwright --exclude-module PySide6 --exclude-module tkinter \
  --hidden-import run --hidden-import fill_links --hidden-import nosimo --hidden-import make_links_template \
  --hidden-import screenshot --hidden-import excel_html --hidden-import stores --hidden-import matching \
  --hidden-import excel --hidden-import config --hidden-import paths \
  --hidden-import phone_matching --hidden-import phone_sites --hidden-import layout \
  tools_main.py

echo "== Приложение (SwiftUI)"
app/build_app.sh >/dev/null
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "build/app.noindex/$APP_NAME.app" "$APP"
RES="$APP/Contents/Resources"
mkdir -p "$RES/tools" "$RES/docs" "$RES/assets"
cp -R dist/tools/monitoring-tools "$RES/tools/"
cp docs/guide.html "$RES/docs/"
cp assets/icon.png "$RES/assets/"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1

echo "== Образ диска"
ln -s /Applications "$STAGE/Applications"
rm -f "dist/$APP_NAME.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "dist/$APP_NAME.dmg" >/dev/null
rm "$STAGE/Applications"
echo "Готово: dist/$APP_NAME.dmg ($(du -h "dist/$APP_NAME.dmg" | cut -f1))"
