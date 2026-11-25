import logging
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .auth import current_user
from .auth import router as auth_router
from .pages import router as pages_router
from .config import get_settings
from .db import check_db, run_migrations
from .web import BASE_DIR, templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("berezhno")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if not settings.secret_key:
        # Без постоянного ключа входы будут сбрасываться при каждом перезапуске.
        settings.secret_key = secrets.token_hex(32)
        log.error("SECRET_KEY не задан в .env — использую временный. Запустите scripts/update.sh.")
    await run_migrations()
    yield


app = FastAPI(title="Бережно", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth_router)
app.include_router(pages_router)


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Формы принимаем только со своего сайта: защита от подделки запросов с чужих страниц."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin is not None:
            domain = get_settings().site_domain
            if urlsplit(origin).hostname not in {domain, f"www.{domain}"}:
                return PlainTextResponse("Запрос отклонён.", status_code=403)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    user = await current_user(request)
    return templates.TemplateResponse(request, "landing.html", {"user": user})


@app.get("/healthz")
async def healthz() -> JSONResponse:
    db_ok = await check_db()
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok},
        status_code=200 if db_ok else 503,
    )
