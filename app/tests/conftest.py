"""Тесты идут на настоящей PostgreSQL. Адрес сервера — в TEST_PG (по умолчанию локальный на порту 55432)."""
import os
import subprocess

import pytest

PG = os.environ.get("TEST_PG", "-h /tmp -p 55432 -U berezhno")
DB = "berezhno_test"

os.environ.update({
    "DATABASE_URL": f"postgresql+asyncpg://berezhno@/{DB}?host=/tmp&port=55432",
    "MAIL_MODE": "log",
    "COOKIE_SECURE": "false",
    "SECRET_KEY": "test-secret",
    "SITE_DOMAIN": "testserver",
    "AI_MODE": "off",
})


def psql(sql: str, db: str = DB) -> str:
    return subprocess.run(["psql", *PG.split(), "-d", db, "-tAc", sql],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    psql(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)", db="postgres")
    psql(f"CREATE DATABASE {DB}", db="postgres")
    yield


@pytest.fixture(scope="session")
def client(fresh_db):
    from fastapi.testclient import TestClient

    from berezhno.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean(request):
    yield
    if "client" in request.fixturenames:
        psql("TRUNCATE users, login_codes, auth_sessions RESTART IDENTITY CASCADE")
        from berezhno import mailer
        mailer.sent_log.clear()
