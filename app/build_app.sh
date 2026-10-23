#!/bin/zsh
# Собирает «Мониторинг цен.app» в build/app.noindex (папки *.noindex Spotlight не индексирует — в поиске
# остаётся только установленное приложение). Без встроенных скриптов приложение находит проект само (~/Developer/monitoring).
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Мониторинг цен"
PROJECT_DIR="$(cd .. && pwd)"
APP="$PROJECT_DIR/build/app.noindex/$APP_NAME.app"
BUILD=".build/bundle"

swift build -c release

rm -rf "$BUILD" && mkdir -p "$BUILD"
swift Tools/make_icon.swift "$BUILD/AppIcon.iconset" >/dev/null
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$BUILD/AppIcon.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/MonitoringApp "$APP/Contents/MacOS/MonitoringApp"
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>local.monitoring.prices</string>
    <key>CFBundleExecutable</key><string>MonitoringApp</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${APP_VERSION:-1.0}</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleDevelopmentRegion</key><string>ru</string>
    <key>LSMinimumSystemVersion</key><string>26.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.business</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1
echo "Готово: $APP"
