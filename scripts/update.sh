#!/usr/bin/env bash
# Обновление «Бережно» до последней версии из GitHub.
# Запуск из папки проекта: bash scripts/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# Сначала забираем новую версию, потом запускаем уже обновлённый скрипт:
# так изменения в самом update.sh применяются сразу.
if [ "${1:-}" != "--pulled" ]; then
  echo "== Забираю новую версию =="
  git pull --ff-only
  exec bash scripts/update.sh --pulled
fi

# Секретный ключ для входа: если его нет в .env, придумываем.
if ! grep -q '^SECRET_KEY=.' .env; then
  sed -i '/^SECRET_KEY=/d' .env
  echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
  echo "Секретный ключ для входа добавлен в .env."
fi

echo "== Пересобираю и перезапускаю =="
sudo docker compose up -d --build
sudo docker image prune -f >/dev/null

echo "Готово."
