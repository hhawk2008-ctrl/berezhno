"""Отправка писем через Yandex Cloud Postbox.

Доступ — по IAM-токену сервисного аккаунта виртуальной машины (роль postbox.sender),
постоянных ключей на сервере нет. В режиме MAIL_MODE=log письма только пишутся в журнал.
"""
import logging
from email.utils import formataddr

import httpx

from . import yc
from .config import get_settings

log = logging.getLogger(__name__)

POSTBOX_URL = "https://postbox.cloud.yandex.net/v2/email/outbound-emails"

# Письма в режиме log — для тестов и локальной разработки.
sent_log: list[dict] = []


class MailError(Exception):
    pass


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
            token = await yc.iam_token(client)
            resp = await client.post(POSTBOX_URL, json=body, headers={"X-YaCloud-SubjectToken": token})
    except httpx.HTTPError as exc:
        log.error("Postbox недоступен: %r", exc)
        raise MailError("postbox unreachable") from exc
    if resp.status_code >= 300:
        log.error("Postbox ответил %s: %s", resp.status_code, resp.text[:500])
        raise MailError(f"postbox status {resp.status_code}")
