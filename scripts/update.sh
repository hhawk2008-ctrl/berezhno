#!/usr/bin/env bash
# Обновление «Бережно» до последней версии из GitHub.
# Запуск из папки проекта: bash scripts/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== Забираю новую версию =="
git pull --ff-only

echo "== Пересобираю и перезапускаю =="
sudo docker compose up -d --build
sudo docker image prune -f >/dev/null

echo "Готово."
