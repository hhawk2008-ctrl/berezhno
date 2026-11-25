from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import check_db

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Бережно", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/healthz")
async def healthz() -> JSONResponse:
    db_ok = await check_db()
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok},
        status_code=200 if db_ok else 503,
    )
