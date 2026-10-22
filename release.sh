#!/bin/zsh
# Выпуск версии на GitLab с этого Mac: оба установщика + страница релиза.
#   ./release.sh 1.3.0
# Шаги: тег v1.3.0 → сборка Mac (build_dmg.sh) и Windows (build_windows_wine.sh) → файлы в реестр пакетов GitLab →
# релиз со ссылками. Описание релиза — .github/release-notes/v1.3.0.md (если есть).
# Ссылки «последняя версия» в README: …/-/releases/permalink/latest/downloads/<файл>.
# Нужно: glab auth login; рабочая копия без незакоммиченных изменений.
set -euo pipefail
cd "$(dirname "$0")"

VERSION=${1:?Использование: ./release.sh 1.3.0}
TAG="v$VERSION"
PROJECT="romanov.evgeniy86%2Fmonitoring-prices"
FILES=(MonitoringPrices-macOS.dmg MonitoringPrices-Windows-Setup.exe)

[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "Есть незакоммиченные изменения"; exit 1; }
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || git tag "$TAG"
git push -q gitlab main "$TAG"

echo "== Mac"
APP_VERSION=$VERSION ./build_dmg.sh | tail -1
cp "dist/Мониторинг цен.dmg" dist/MonitoringPrices-macOS.dmg
echo "== Windows (Wine)"
APP_VERSION=$VERSION ./build_windows_wine.sh | grep -E "^==|Готово"

echo "== GitLab"
PACKAGES="https://gitlab.com/api/v4/projects/$PROJECT/packages/generic/monitoring-prices/$VERSION"
links=()
for f in $FILES; do
  glab api -X PUT "projects/$PROJECT/packages/generic/monitoring-prices/$VERSION/$f" \
    --input "dist/$f" -H "Content-Type: application/octet-stream" >/dev/null
  links+=("{\"name\":\"$f\",\"url\":\"$PACKAGES/$f\",\"direct_asset_path\":\"/$f\",\"link_type\":\"package\"}")
done
notes=".github/release-notes/$TAG.md"
[[ -f "$notes" ]] || notes=/dev/null
glab release create "$TAG" --name "Мониторинг цен $TAG" --notes-file "$notes" --assets-links "[${(j:,:)links}]"
echo "Готово: https://gitlab.com/romanov.evgeniy86/monitoring-prices/-/releases/$TAG"
