#!/bin/zsh
# Выпуск версии одной командой — на GitHub и GitLab одни и те же установщики.
#   ./release.sh 1.3.0           сборка в GitHub Actions (Windows проверяется на настоящей Windows), затем копия на GitLab
#   ./release.sh 1.3.0 --local   сборка на этом Mac (Windows — через Wine), если Actions недоступны
# Описание релиза — .github/release-notes/v1.3.0.md (если есть).
# Ссылки «последняя версия» в README: GitLab …/-/releases/permalink/latest/downloads/<файл>.
# Нужно: gh auth login, glab auth login; рабочая копия без незакоммиченных изменений.
set -euo pipefail
cd "$(dirname "$0")"

VERSION=${1:?Использование: ./release.sh 1.3.0 [--local]}
LOCAL=${2:-}
TAG="v$VERSION"
GITLAB_PROJECT="romanov.evgeniy86%2Fmonitoring-prices"
FILES=(MonitoringPrices-macOS.dmg MonitoringPrices-Windows-Setup.exe)
NOTES=".github/release-notes/$TAG.md"
[[ -f "$NOTES" ]] || NOTES=/dev/null
OUT="dist/release-$VERSION"
mkdir -p "$OUT"

[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "Есть незакоммиченные изменения"; exit 1; }
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || git tag "$TAG"
git push -q gitlab main "$TAG"

if [[ "$LOCAL" == "--local" ]]; then
  echo "== Сборка на этом Mac"
  APP_VERSION=$VERSION ./build_dmg.sh | tail -1
  cp "dist/Мониторинг цен.dmg" "$OUT/MonitoringPrices-macOS.dmg"
  APP_VERSION=$VERSION ./build_windows_wine.sh | grep -E "^==|Готово"
  cp dist/MonitoringPrices-Windows-Setup.exe "$OUT/"
  git push -q origin main
  git push -q origin "$TAG" || true
  # релиз на GitHub — из этих же файлов (сборка Actions по тегу его тоже создаст; кто первый — тот и создал)
  gh release view "$TAG" >/dev/null 2>&1 ||
    gh release create "$TAG" "$OUT/${FILES[1]}" "$OUT/${FILES[2]}" --title "Мониторинг цен $TAG" --notes-file "$NOTES"
else
  echo "== Сборка в GitHub Actions"
  git push -q origin main "$TAG"
  run=""
  for _ in {1..30}; do  # запуск по тегу появляется через несколько секунд
    run=$(gh run list --workflow build.yml --branch "$TAG" --limit 1 --json databaseId --jq '.[0].databaseId // empty')
    [[ -n "$run" ]] && break
    sleep 5
  done
  [[ -n "$run" ]] || { echo "Сборка по тегу $TAG не запустилась — повторите с --local"; exit 1; }
  echo "https://github.com/romanovevgeniy/monitoring-prices/actions/runs/$run"
  gh run watch "$run" --exit-status --interval 30 >/dev/null ||
    { echo "Сборка в Actions не прошла (см. ссылку выше) — исправьте или повторите с --local"; exit 1; }
  gh release download "$TAG" --dir "$OUT" --clobber --pattern '*.dmg' --pattern '*.exe'
fi

echo "== GitLab"
PACKAGES="https://gitlab.com/api/v4/projects/$GITLAB_PROJECT/packages/generic/monitoring-prices/$VERSION"
links=()
for f in $FILES; do
  glab api -X PUT "projects/$GITLAB_PROJECT/packages/generic/monitoring-prices/$VERSION/$f" \
    --input "$OUT/$f" -H "Content-Type: application/octet-stream" >/dev/null
  links+=("{\"name\":\"$f\",\"url\":\"$PACKAGES/$f\",\"direct_asset_path\":\"/$f\",\"link_type\":\"package\"}")
done
glab release create "$TAG" --name "Мониторинг цен $TAG" --notes-file "$NOTES" --assets-links "[${(j:,:)links}]" >/dev/null
echo "Готово:"
echo "  https://gitlab.com/romanov.evgeniy86/monitoring-prices/-/releases/$TAG"
echo "  https://github.com/romanovevgeniy/monitoring-prices/releases/tag/$TAG"
