#!/usr/bin/env bash
# Первая установка «Бережно» на сервер.
# Запуск из папки проекта: bash scripts/install.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== 1/5. Устанавливаю Docker =="
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 git openssl curl
sudo systemctl enable --now docker

# Зеркало Docker Hub в России (Timeweb): из Yandex Cloud Docker Hub и зеркало Google не отвечают.
if [ ! -f /etc/docker/daemon.json ] || grep -q "mirror.gcr.io" /etc/docker/daemon.json; then
  echo '{ "registry-mirrors": ["https://dockerhub.timeweb.cloud"] }' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker
fi

echo "== 2/5. Готовлю настройки (.env) =="
if [ ! -f .env ]; then
  cp .env.example .env
  password="$(openssl rand -hex 24)"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${password}/" .env
  chmod 600 .env
  echo "Файл .env создан, пароль базы данных придуман автоматически."
else
  echo "Файл .env уже есть — оставляю как есть."
fi

# Секретный ключ для входа: если его нет в .env, придумываем.
if ! grep -q '^SECRET_KEY=.' .env; then
  sed -i '/^SECRET_KEY=/d' .env
  echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
  echo "Секретный ключ для входа добавлен в .env."
fi

domain="$(grep '^SITE_DOMAIN=' .env | cut -d= -f2)"

echo "== 3/5. Сертификат https =="
bash scripts/cert.sh

echo "== 4/5. Собираю и запускаю сервис (первый раз займёт 3–5 минут) =="
sudo docker compose up -d --build

echo "== 5/5. Проверяю, что сайт отвечает =="
for i in $(seq 1 12); do
  if curl -fsS --max-time 10 "https://${domain}/healthz" >/dev/null 2>&1; then
    echo
    echo "Готово: https://${domain} работает."
    exit 0
  fi
  sleep 10
done

echo
echo "Сервис запущен, но сайт пока не ответил по https://${domain}."
echo "Подождите минуту и откройте сайт в браузере."
echo "Если не откроется, пришлите вывод команды:  sudo docker compose logs --tail=50"
