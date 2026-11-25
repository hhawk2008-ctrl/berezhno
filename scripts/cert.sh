#!/usr/bin/env bash
# Сертификат https от Let's Encrypt с проверкой домена через DNS в REG.RU.
# Первый запуск получает сертификат, следующие продлевают его, если до конца срока меньше 30 дней.
# Скрипт сам добавляет еженедельный автозапуск (cron), поэтому продлевать вручную не нужно.
# Запуск из папки проекта: bash scripts/cert.sh
set -euo pipefail
# Версия lego закреплена: в lego 5 другие параметры запуска.
trap 'echo "cert.sh: ошибка в строке $LINENO" >&2' ERR

cd "$(dirname "$0")/.."
project_dir="$PWD"

# Если строки в .env нет, возвращаем пустое значение, а не ошибку.
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2- || true; }

domain="$(env_value SITE_DOMAIN)"
email="$(env_value ACME_EMAIL)"
email="${email:-privet@${domain}}"
echo "Сертификат для ${domain}: проверяю."

if [ -z "$(env_value REGRU_USERNAME)" ] || [ -z "$(env_value REGRU_PASSWORD)" ]; then
  echo "В файле .env не заполнены REGRU_USERNAME и REGRU_PASSWORD — см. шаг 15 инструкции." >&2
  exit 1
fi

mkdir -p certs
cert="certs/certificates/${domain}.crt"

# lego создаёт файлы от имени root с закрытыми правами, поэтому проверяем их через sudo.
if sudo test -f "$cert"; then
  action=(renew --days 30)
  before="$(sudo sha256sum "$cert" | cut -d' ' -f1)"
else
  action=(run)
  before=""
  echo "Получаю сертификат для ${domain} и www.${domain}."
  echo "Проверка через DNS может занять от 2 до 30 минут — не закрывайте окно."
fi

# GODEBUG=tlsmlkem=0 — короткое приветствие TLS без постквантового ключа:
# с длинным на части адресов из облака соединение зависает (TLS handshake timeout).
sudo docker run --rm --network host \
  --env-file .env \
  -e GODEBUG=tlsmlkem=0 \
  -e REGRU_PROPAGATION_TIMEOUT=1800 \
  -e REGRU_POLLING_INTERVAL=30 \
  -v "${project_dir}/certs:/data" \
  goacme/lego:v4.35.2 \
  --accept-tos --email "$email" --dns regru \
  --domains "$domain" --domains "www.${domain}" \
  --path /data "${action[@]}"

after="$(sudo sha256sum "$cert" | cut -d' ' -f1)"

# Если сертификат новый или обновился и Caddy уже запущен — перезапускаем его, чтобы он взял новый файл.
if [ "$before" != "$after" ] && [ -n "$(sudo docker compose ps --status running -q caddy 2>/dev/null)" ]; then
  sudo docker compose up -d caddy
  sudo docker compose restart caddy
  echo "Caddy перезапущен с новым сертификатом."
fi

# Еженедельное продление: по понедельникам в 04:17.
cron_line="17 4 * * 1 cd ${project_dir} && bash scripts/cert.sh >> \$HOME/cert.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qF "scripts/cert.sh"; then
  ( crontab -l 2>/dev/null; echo "$cron_line" ) | crontab -
  echo "Автопродление сертификата включено (раз в неделю)."
fi

echo "Сертификат в порядке."
