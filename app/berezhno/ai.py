"""Запросы к YandexGPT. Ответ просим в JSON и разбираем осторожно: модель может ошибиться в формате."""
import json
import logging
import re

import httpx

from . import yc
from .config import get_settings

log = logging.getLogger(__name__)

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class AIError(Exception):
    pass


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group())
        raise


async def complete_json(system: str, user: str, *, temperature: float = 0.3, max_tokens: int = 1500) -> dict:
    settings = get_settings()
    if settings.ai_mode != "yandex":
        raise AIError("ai disabled")
    body = {
        "modelUri": f"gpt://{settings.folder_id}/{settings.yandex_gpt_model}",
        "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": str(max_tokens)},
        "messages": [{"role": "system", "text": system}, {"role": "user", "text": user}],
        "jsonObject": True,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            token = await yc.iam_token(client)
            resp = await client.post(COMPLETION_URL, json=body, headers={
                "Authorization": f"Bearer {token}", "x-folder-id": settings.folder_id})
    except httpx.HTTPError as exc:
        log.error("YandexGPT недоступен: %r", exc)
        raise AIError("unreachable") from exc
    if resp.status_code != 200:
        log.error("YandexGPT ответил %s: %s", resp.status_code, resp.text[:500])
        raise AIError(f"status {resp.status_code}")
    try:
        text = resp.json()["result"]["alternatives"][0]["message"]["text"]
        return _parse_json(text)
    except (KeyError, IndexError, ValueError) as exc:
        log.error("Не разобрал ответ YandexGPT: %s", resp.text[:500])
        raise AIError("bad response") from exc


PLAN_SYSTEM = """Ты помогаешь человеку в сервисе «Бережно» — помощнике на пути к цели без гонки и упрёков.
Подход основан на когнитивно-поведенческой терапии: маленькие конкретные шаги, план «если — то», бережное отношение к себе.

Тебе дают цель человека и его ответы на уточняющие вопросы. Составь план.

Правила:
- Этапов от 3 до 5. Каждый этап — короткая конкретная формулировка, до 8 слов.
- Первый шаг делается сегодня или завтра и занимает 10–15 минут. Он конкретный и физический:
  что именно открыть, написать, найти. Не «начать заниматься», а «открыть курс и посмотреть, где остановились».
- План «если — то» привязан к реальной ситуации человека: «Если …, то сразу …». Учитывай, что мешало раньше.
- Пиши на «вы», тепло и просто, без терминов. Не используй слова: достигать, продуктивность, дисциплина,
  лень, челлендж, прокачать, срыв, провал. Избегай глаголов прошедшего времени с родом (сделал/сделала).
- Поле topic: "crisis", если в тексте есть мысли о самоубийстве, самоповреждении или желание не жить;
  "forbidden", если цель про зависимости (алкоголь, курение, наркотики, азартные игры), вес, диеты и питание
  или долги и кредиты; иначе "ok".

Ответь только JSON такого вида:
{"topic": "ok", "stages": ["...", "..."], "first_step": {"title": "...", "minutes": 10}, "if_then": "Если ..., то ..."}"""


async def make_plan(goal: str, answers: dict[str, str]) -> dict:
    lines = [f"Цель: {goal}"] + [f"{q} — {a}" for q, a in answers.items() if a]
    data = await complete_json(PLAN_SYSTEM, "\n".join(lines))
    stages = [str(s).strip() for s in data.get("stages") or [] if str(s).strip()][:5]
    step = data.get("first_step") or {}
    try:
        minutes = int(step.get("minutes") or 15)
    except (TypeError, ValueError):
        minutes = 15
    return {
        "topic": data.get("topic") if data.get("topic") in {"ok", "forbidden", "crisis"} else "ok",
        "stages": stages,
        "first_step": {"title": str(step.get("title") or "").strip(), "minutes": max(5, min(minutes, 60))},
        "if_then": str(data.get("if_then") or "").strip(),
    }
