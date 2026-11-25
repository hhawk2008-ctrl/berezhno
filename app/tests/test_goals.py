import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from berezhno import mailer, pages

from .conftest import psql

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
PLAN = {"topic": "ok", "stages": ["Вернуться в курс", "Пройти уроки 5–8", "Сдать тест"],
        "first_step": {"title": "Открыть курс и найти урок 4", "minutes": 10},
        "if_then": "Если в 21:00 я дома, то сразу открываю курс"}


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(pages, "local_now", lambda user: NOW)


@pytest.fixture
def ai_plan(monkeypatch):
    calls = []

    async def fake(goal, answers):
        calls.append((goal, answers))
        return dict(PLAN)

    monkeypatch.setattr(pages.ai, "make_plan", fake)
    return calls


def login(client, email="olga@example.ru"):
    client.post("/logout")
    client.post("/login", data={"email": email})
    code = re.search(r"\d{6}", mailer.sent_log[-1]["subject"]).group()
    r = client.post("/login/code", data={"code": code}, follow_redirects=False)
    assert r.headers["location"] == "/today"


def onboard(client, name="Ольга"):
    return client.post("/welcome", data={"name": name, "morning": "08:30", "evening": "21:30",
                                         "tz": "Europe/Moscow", "selfhelp": "1", "pd": "1"}, follow_redirects=False)


def make_goal(client):
    client.post("/goal/new", data={"title": "Хочу пройти курс по Excel"})
    client.post("/goal/new/questions", data={"done": "сертификат", "deadline": "к 1 марта", "time": "3 часа",
                                              "obstacle": "стыдно возвращаться"})
    return client.post("/goal/new/plan", data={
        "stage0": PLAN["stages"][0], "stage1": PLAN["stages"][1], "stage2": PLAN["stages"][2],
        "step_title": PLAN["first_step"]["title"], "step_minutes": "10", "if_then": PLAN["if_then"]},
        follow_redirects=False)


def test_welcome_required_and_consents(client):
    login(client)
    assert client.get("/today", follow_redirects=False).headers["location"] == "/welcome"
    r = client.post("/welcome", data={"name": "Ольга", "tz": "Europe/Moscow"})
    assert r.status_code == 400 and "обе галочки" in r.text
    r = onboard(client)
    assert r.headers["location"] == "/goal/new"
    assert psql("SELECT name, evening_time, timezone, consent_pd_at IS NOT NULL FROM users") == \
        "Ольга|21:30:00|Europe/Moscow|t"
    assert client.get("/today", follow_redirects=False).headers["location"] == "/goal/new"


def test_goal_flow_with_ai_and_checkin(client, ai_plan):
    login(client)
    onboard(client)
    r = client.post("/goal/new", data={"title": "Хочу пройти курс по Excel"}, follow_redirects=False)
    assert r.headers["location"] == "/goal/new/questions"
    r = client.post("/goal/new/questions", data={"done": "сертификат", "obstacle": "стыдно возвращаться"},
                    follow_redirects=False)
    assert r.headers["location"] == "/goal/new/plan"
    assert ai_plan[0][1]["Что мешало раньше, если вы уже пробовали?"] == "стыдно возвращаться"
    page = client.get("/goal/new/plan").text
    assert "Пройти уроки 5–8" in page and "Открыть курс и найти урок 4" in page

    r = make_goal(client)
    assert r.headers["location"] == "/start"
    assert "Сегодня — один шаг на 10 минут" in client.get("/start").text
    assert psql("SELECT main_risk, status FROM goals") == "стыдно возвращаться|active"

    today = client.get("/today").text
    assert "Открыть курс и найти урок 4" in today and "Как прошло?" in today
    assert 'aria-current="page">Сегодня' in today

    step_id = psql("SELECT id FROM steps")
    r = client.post("/today/checkin", data={"step_id": step_id, "result": "done"}, follow_redirects=False)
    assert r.headers["location"] == "/today?r=done"
    today = client.get("/today?r=done").text
    assert "Записано в копилку" in today and "Первый шаг" in today and "Выбрать шаг на завтра" in today
    assert "Открыть курс и найти урок 4" in client.get("/evidence").text

    # повторная отметка того же шага ничего не меняет
    client.post("/today/checkin", data={"step_id": step_id, "result": "not_done"})
    assert psql(f"SELECT status FROM steps WHERE id = {step_id}") == "done"

    r = client.post("/step/next", data={"title": "Урок 5, первые 15 минут", "minutes": "15", "if_then": ""},
                    follow_redirects=False)
    assert r.headers["location"] == "/today"
    assert psql("SELECT day FROM steps ORDER BY id DESC LIMIT 1") == "2026-11-26"
    assert "Шаг на 26 ноября" in client.get("/today").text
    assert "Пройти уроки 5–8" in client.get("/goal").text


def test_not_done_suggests_smaller_step(client, ai_plan):
    login(client)
    onboard(client)
    make_goal(client)
    step_id = psql("SELECT id FROM steps")
    client.post("/today/checkin", data={"step_id": step_id, "result": "not_done"})
    assert "Сегодня не получилось" in client.get("/today?r=not_done").text
    page = client.get("/step/next").text
    assert "вдвое меньше" in page and 'value="5"' in page
    client.post("/step/next", data={"title": "Открыть курс", "minutes": "20", "action": "half"})
    assert psql("SELECT minutes, day FROM steps ORDER BY id DESC LIMIT 1") == "10|2026-11-26"
    assert psql("SELECT count(*) FROM evidence") == "0"


def test_overdue_step_and_energy(client, ai_plan):
    login(client)
    onboard(client)
    make_goal(client)
    psql("UPDATE steps SET day = '2026-11-24'")
    assert "остался без отметки" in client.get("/today").text
    client.post("/today/energy", data={"value": "3"})
    assert 'value="3" aria-pressed="true"' in client.get("/today").text
    assert psql("SELECT value FROM day_energy") == "3"


def test_ai_unavailable_gives_manual_plan(client):
    login(client)
    onboard(client)
    client.post("/goal/new", data={"title": "Выучить 500 английских слов"})
    client.post("/goal/new/questions", data={})
    page = client.get("/goal/new/plan").text
    assert "Помощник сейчас не ответил" in page
    r = client.post("/goal/new/plan", data={"step_title": "Скачать приложение"})
    assert r.status_code == 400 and "хотя бы один этап" in r.text
    r = client.post("/goal/new/plan", data={"stage0": "Первые 100 слов", "step_title": "Скачать приложение"},
                    follow_redirects=False)
    assert r.headers["location"] == "/start"


def test_forbidden_topic(client):
    login(client)
    onboard(client)
    r = client.post("/goal/new", data={"title": "Хочу похудеть на 10 кг"})
    assert "пока не помогает" in r.text
    assert psql("SELECT count(*) FROM goals") == "0"


def test_ai_flags_forbidden(client, monkeypatch):
    async def fake(goal, answers):
        return {**PLAN, "topic": "forbidden"}

    monkeypatch.setattr(pages.ai, "make_plan", fake)
    login(client)
    onboard(client)
    client.post("/goal/new", data={"title": "Разобраться с финансами"})
    r = client.post("/goal/new/questions", data={})
    assert "пока не помогает" in r.text
    assert psql("SELECT status FROM goals") == "draft"


def test_crisis_in_answers(client):
    login(client)
    onboard(client)
    client.post("/goal/new", data={"title": "Найти работу"})
    r = client.post("/goal/new/questions", data={"obstacle": "иногда не хочу жить"}, follow_redirects=False)
    assert r.headers["location"] == "/help-now"
    assert psql("SELECT crisis_at IS NOT NULL FROM users") == "t"
    page = client.get("/help-now").text
    assert "112" in page and "989-50-50" in page


def test_cannot_check_someone_elses_step(client, ai_plan):
    login(client, "first@example.ru")
    onboard(client)
    make_goal(client)
    step_id = psql("SELECT id FROM steps")
    login(client, "second@example.ru")
    onboard(client)
    client.post("/today/checkin", data={"step_id": step_id, "result": "done"})
    assert psql(f"SELECT status FROM steps WHERE id = {step_id}") == "planned"


def test_help_and_policy_are_public(client):
    client.post("/logout")
    assert client.get("/help-now").status_code == 200
    assert client.get("/privacy-policy").status_code == 200
