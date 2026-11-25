"""Отправка писем через Yandex Cloud Postbox.

Доступ — по IAM-токену сервисного аккаунта виртуальной машины (роль postbox.sender),
постоянных ключей на сервере нет. В режиме MAIL_MODE=log письма только пишутся в журнал.
"""
import logging
import time
from email.utils import formataddr

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

METADATA_TOKEN_URL = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
POSTBOX_URL = "https://postbox.cloud.yandex.net/v2/email/outbound-emails"

# Письма в режиме log — для тестов и локальной разработки.
sent_log: list[dict] = []

_token: str | None = None
_token_expires: float = 0.0


class MailError(Exception):
    pass


async def _iam_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires
    if _token and time.monotonic() < _token_expires - 300:
        return _token
    resp = await client.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expires = time.monotonic() + int(data.get("expires_in", 3600))
    return _token


async def send_email(to: str, subject: str, text: str, html: str) -> None:
    settings = get_settings()
    if settings.mail_mode == "log":
        sent_log.append({"to": to, "subject": subject, "text": text, "html": html})
        log.info("Письмо (режим log) для %s: %s", to, subject)
        return

    utf8 = "UTF-8"
    body = {
        "FromEmailAddress": formataddr((settings.mail_from_name, settings.mail_from_address), charset="utf-8"),
        "Destination": {"ToAddresses": [to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": utf8},
                "Body": {"Text": {"Data": text, "Charset": utf8}, "Html": {"Data": html, "Charset": utf8}},
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token = await _iam_token(client)
            resp = await client.post(POSTBOX_URL, json=body, headers={"X-YaCloud-SubjectToken": token})
    except httpx.HTTPError as exc:
        log.error("Postbox недоступен: %r", exc)
        raise MailError("postbox unreachable") from exc
    if resp.status_code >= 300:
        log.error("Postbox ответил %s: %s", resp.status_code, resp.text[:500])
        raise MailError(f"postbox status {resp.status_code}")
