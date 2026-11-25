import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import get_settings

log = logging.getLogger(__name__)

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
