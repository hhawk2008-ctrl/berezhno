import re

from berezhno import mailer

from .conftest import psql


def last_code() -> str:
    return re.search(r"\d{6}", mailer.sent_log[-1]["subject"]).group()


def request_code(client, email="Anna@Example.ru "):
    return client.post("/login", data={"email": email}, follow_redirects=False)


def test_landing_and_health(client):
    r = client.get("/")
    assert r.status_code == 200 and "Войти" in r.text
    assert client.get("/healthz").json() == {"status": "ok", "db": True}


def test_today_requires_login(client):
    r = client.get("/today", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_bad_email(client):
    r = client.post("/login", data={"email": "anna@"})
    assert r.status_code == 400 and "опечатка" in r.text
    assert mailer.sent_log == []


def test_full_login_flow(client):
    r = request_code(client)
    assert r.status_code == 303 and r.headers["location"] == "/login/code?status=sent"
    mail = mailer.sent_log[-1]
    assert mail["to"] == "anna@example.ru"
    code = last_code()
    assert code in mail["html"] and code in mail["text"] and "Код действует 15 минут" in mail["html"]

    page = client.get("/login/code")
    assert "anna@example.ru" in page.text

    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/login/code", data={"code": wrong})
    assert r.status_code == 400 and "осталось попыток: 4" in r.text

    r = client.post("/login/code", data={"code": f"{code[:3]} {code[3:]}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/today"
    assert "anna@example.ru" in client.get("/today").text
    assert client.get("/login", follow_redirects=False).headers["location"] == "/today"
    assert "Перейти к своему дню" in client.get("/").text

    # Код одноразовый.
    assert psql("SELECT count(*) FROM login_codes WHERE used_at IS NOT NULL") == "1"

    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/today", follow_redirects=False).headers["location"] == "/login"
    assert psql("SELECT count(*) FROM auth_sessions") == "0"
    assert psql("SELECT count(*) FROM users") == "1"


def test_resend_waits_a_minute(client):
    request_code(client)
    r = request_code(client)
    assert r.headers["location"] == "/login/code?status=wait"
    assert len(mailer.sent_log) == 1
    assert "меньше минуты назад" in client.get("/login/code?status=wait").text


def test_new_code_cancels_old_one(client):
    request_code(client)
    old = last_code()
    psql("UPDATE login_codes SET created_at = now() - interval '2 minutes'")
    request_code(client)
    new = last_code()
    if old != new:
        r = client.post("/login/code", data={"code": old})
        assert r.status_code == 400
    r = client.post("/login/code", data={"code": new}, follow_redirects=False)
    assert r.headers["location"] == "/today"
    client.post("/logout")


def test_too_many_attempts(client):
    request_code(client)
    code = last_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/login/code", data={"code": wrong})
    r = client.post("/login/code", data={"code": code})
    assert r.status_code == 429 and "слишком много попыток" in r.text


def test_hourly_limit(client):
    psql("INSERT INTO login_codes (email, code_hash, expires_at, created_at) "
         "SELECT 'anna@example.ru', 'x', now(), now() - interval '5 minutes' FROM generate_series(1, 5)")
    r = request_code(client)
    assert r.status_code == 429 and "через час" in r.text


def test_expired_code(client):
    request_code(client)
    psql("UPDATE login_codes SET expires_at = now() - interval '1 second'")
    r = client.post("/login/code", data={"code": last_code()})
    assert r.status_code == 400 and "закончился" in r.text


def test_code_page_without_cookie(client):
    client.cookies.clear()
    r = client.get("/login/code", follow_redirects=False)
    assert r.headers["location"] == "/login"


def test_foreign_origin_rejected(client):
    r = client.post("/login", data={"email": "anna@example.ru"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/login", data={"email": "anna@example.ru"}, headers={"Origin": "http://testserver"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_mail_failure(client, monkeypatch):
    from berezhno import auth

    async def broken(**_):
        raise mailer.MailError("down")

    monkeypatch.setattr(auth, "send_email", broken)
    r = request_code(client)
    assert r.status_code == 502 and "Не получилось отправить письмо" in r.text
    assert psql("SELECT count(*) FROM login_codes") == "0"


def test_migrations_are_idempotent(client):
    from berezhno.db import run_migrations

    client.portal.call(run_migrations)  # тот же цикл событий, что у приложения
    assert psql("SELECT count(*) FROM schema_migrations") == "1"
    assert client.get("/healthz").status_code == 200
