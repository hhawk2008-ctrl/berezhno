#!/usr/bin/env bash
# Сертификат https выпускает и сам продлевает Yandex Certificate Manager (через Let's Encrypt).
# Этот скрипт скачивает актуальную версию сертификата на сервер и перезапускает Caddy, если она поменялась.
# Доступ — через сервисный аккаунт, привязанный к виртуальной машине (шаг 15 инструкции): ключей на сервере нет.
# Скрипт сам добавляет ежедневный автозапуск (cron).
# Запуск из папки проекта: bash scripts/cert.sh
set -euo pipefail
trap 'echo "cert.sh: ошибка в строке $LINENO" >&2' ERR

cd "$(dirname "$0")/.."
project_dir="$PWD"

# Если строки в .env нет, возвращаем пустое значение, а не ошибку.
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2- || true; }

domain="$(env_value SITE_DOMAIN)"
cert_id="$(env_value CM_CERTIFICATE_ID)"
echo "Сертификат для ${domain}: проверяю."

if [ -z "$cert_id" ]; then
  echo "В файле .env не заполнен CM_CERTIFICATE_ID — см. шаг 15 инструкции." >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Временный токен сервисного аккаунта виртуальной машины.
if ! curl -sf --max-time 10 -H 'Metadata-Flavor: Google' \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token -o "$tmp/token.json"; then
  echo "Не получилось взять токен: к виртуальной машине не привязан сервисный аккаунт (шаг 15)." >&2
  exit 1
fi
token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' "$tmp/token.json")"

code="$(curl -s --max-time 30 -o "$tmp/content.json" -w '%{http_code}' \
  -H "Authorization: Bearer ${token}" \
  "https://data.certificate-manager.api.cloud.yandex.net/certificate-manager/v1/certificates/${cert_id}:getContent")"
if [ "$code" != "200" ]; then
  echo "Certificate Manager ответил кодом ${code}:" >&2
  head -c 400 "$tmp/content.json" >&2; echo >&2
  echo "Если сертификат ещё не выпущен (статус не ISSUED), подождите и запустите скрипт снова." >&2
  exit 1
fi

python3 - "$tmp" <<'PY'
import json, os, sys
d = sys.argv[1]
data = json.load(open(os.path.join(d, "content.json")))
chain = "\n".join(part.strip() for part in data["certificateChain"]) + "\n"
open(os.path.join(d, "crt"), "w").write(chain)
open(os.path.join(d, "key"), "w").write(data["privateKey"].strip() + "\n")
PY

dest="certs/certificates/${domain}"
sudo mkdir -p certs/certificates
if sudo cmp -s "$tmp/crt" "${dest}.crt"; then
  echo "Сертификат не менялся."
else
  sudo install -m 600 "$tmp/key" "${dest}.key"
  sudo install -m 600 "$tmp/crt" "${dest}.crt"
  echo "Сертификат обновлён."
  # Пересоздаём Caddy, чтобы он взял новый сертификат (и новые настройки, если они поменялись).
  if [ -n "$(sudo docker compose ps --status running -q caddy 2>/dev/null)" ]; then
    sudo docker compose up -d --force-recreate caddy
    echo "Caddy перезапущен."
  fi
fi

# Ежедневная проверка в 04:17. Старую строку (если была) заменяем.
cron_line="17 4 * * * cd ${project_dir} && bash scripts/cert.sh >> \$HOME/cert.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qxF "$cron_line"; then
  ( crontab -l 2>/dev/null | grep -vF "scripts/cert.sh" || true; echo "$cron_line" ) | crontab -
  echo "Автопроверка сертификата включена (раз в день)."
fi

echo "Сертификат в порядке."
