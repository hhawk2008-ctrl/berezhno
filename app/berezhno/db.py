import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import get_settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

engine: AsyncEngine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def check_db() -> bool:
    """True, если база отвечает. Нужна для страницы проверки /healthz."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — для проверки важен только факт ответа
        log.warning("База данных не отвечает: %s", exc)
        return False


async def run_migrations() -> None:
    """Применяет новые файлы из папки migrations по порядку имён. Каждый файл — один раз."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(724001)"))
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        ))
        done = set((await conn.execute(text("SELECT name FROM schema_migrations"))).scalars())
        raw = (await conn.get_raw_connection()).driver_connection
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            # В файле может быть несколько команд — их выполняет сам драйвер asyncpg.
            await raw.execute(path.read_text(encoding="utf-8"))
            await conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": path.name})
            log.info("Применена миграция %s", path.name)
