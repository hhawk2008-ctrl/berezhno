"""Вход по коду на почту: /login → письмо с кодом → /login/code → сеанс в куке."""
import hmac
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from . import security
from .config import get_settings
from .db import SessionLocal
from .mailer import MailError, send_email
from .models import AuthSession, LoginCode, User
from .web import templates

log = logging.getLogger(__name__)
router = APIRouter()

SESSION_COOKIE = "bz_session"
EMAIL_COOKIE = "bz_login_email"
SESSION_DAYS = 180
CODE_MINUTES = 15
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
CODES_PER_HOUR_EMAIL = 5
CODES_PER_HOUR_IP = 20

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _secret() -> str:
    return get_settings().secret_key


def _set_cookie(resp: Response, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, httponly=True, secure=get_settings().cookie_secure,
                    samesite="lax", path="/")


async def current_user(request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    async with SessionLocal() as db:
        return (await db.execute(
            select(User).join(AuthSession, AuthSession.user_id == User.id).where(
                AuthSession.token_hash == security.hash_token(token),
                AuthSession.expires_at > func.now(),
            )
        )).scalar_one_or_none()


def _login_page(request: Request, *, email: str = "", error: str = "", status: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"email": email, "error": error}, status_code=status)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    if await current_user(request):
        return RedirectResponse("/today", status_code=303)
    return _login_page(request)


@router.post("/login")
async def login_send(request: Request, email: str = Form("")) -> Response:
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return _login_page(request, email=email, status=400,
                           error="Похоже, в адресе опечатка. Проверьте, пожалуйста, и попробуйте ещё раз.")
    ip = request.client.host if request.client else None

    async with SessionLocal() as db:
        recent, last_minute = (await db.execute(
            select(
                func.count().filter(LoginCode.created_at > func.now() - timedelta(hours=1)),
                func.coalesce(func.bool_or(LoginCode.created_at > func.now() - timedelta(seconds=RESEND_SECONDS)), False),
            ).where(LoginCode.email == email)
        )).one()
        ip_recent = (await db.execute(
            select(func.count()).where(LoginCode.ip == ip, LoginCode.created_at > func.now() - timedelta(hours=1))
        )).scalar_one() if ip else 0

        if last_minute:
            resp = RedirectResponse("/login/code?status=wait", status_code=303)
            _set_cookie(resp, EMAIL_COOKIE, security.sign(_secret(), email), CODE_MINUTES * 60)
            return resp
        if recent >= CODES_PER_HOUR_EMAIL or ip_recent >= CODES_PER_HOUR_IP:
            return _login_page(request, email=email, status=429,
                               error="Кодов было запрошено слишком много. Попробуйте, пожалуйста, через час.")

        code = security.new_code()
        # Старые коды для этой почты больше не действуют — работает только последний.
        await db.execute(update(LoginCode).where(
            LoginCode.email == email, LoginCode.used_at.is_(None), LoginCode.expires_at > func.now()
        ).values(expires_at=func.now()))
        row = LoginCode(email=email, code_hash=security.hash_code(_secret(), email, code), ip=ip,
                        expires_at=func.now() + timedelta(minutes=CODE_MINUTES))
        db.add(row)
        await db.commit()

        context = {"code": code, "minutes": CODE_MINUTES,
                   "preheader": f"Код действует {CODE_MINUTES} минут. Если вы его не запрашивали, ничего делать не нужно."}
        try:
            await send_email(
                to=email,
                subject=f"Ваш код для входа: {code}",
                text=templates.get_template("email/login_code.txt").render(context),
                html=templates.get_template("email/login_code.html").render(context),
            )
        except MailError:
            await db.delete(row)
            await db.commit()
            return _login_page(request, email=email, status=502,
                               error="Не получилось отправить письмо. Попробуйте, пожалуйста, ещё раз через минуту.")

    resp = RedirectResponse("/login/code?status=sent", status_code=303)
    _set_cookie(resp, EMAIL_COOKIE, security.sign(_secret(), email), CODE_MINUTES * 60)
    return resp


def _code_page(request: Request, email: str, *, notice: str = "", error: str = "", status: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, "login_code.html",
                                      {"email": email, "notice": notice, "error": error}, status_code=status)


@router.get("/login/code", response_class=HTMLResponse)
async def code_form(request: Request, status: str = "") -> Response:
    email = security.unsign(_secret(), request.cookies.get(EMAIL_COOKIE), CODE_MINUTES * 60)
    if not email:
        return RedirectResponse("/login", status_code=303)
    notice = ""
    if status == "wait":
        notice = "Код уже отправлен меньше минуты назад. Проверьте почту, а новый можно будет запросить чуть позже."
    return _code_page(request, email, notice=notice)


@router.post("/login/code")
async def code_check(request: Request, code: str = Form("")) -> Response:
    email = security.unsign(_secret(), request.cookies.get(EMAIL_COOKIE), CODE_MINUTES * 60)
    if not email:
        return RedirectResponse("/login", status_code=303)
    code = re.sub(r"\D", "", code)

    async with SessionLocal() as db:
        row = (await db.execute(
            select(LoginCode).where(
                LoginCode.email == email, LoginCode.used_at.is_(None), LoginCode.expires_at > func.now()
            ).order_by(LoginCode.created_at.desc()).limit(1).with_for_update()
        )).scalar_one_or_none()
        if row is None:
            return _code_page(request, email, status=400,
                              error="Срок действия кода закончился. Запросите, пожалуйста, новый — это займёт минуту.")
        if row.attempts >= MAX_ATTEMPTS:
            return _code_page(request, email, status=429,
                              error="Было слишком много попыток. Запросите, пожалуйста, новый код.")
        if not hmac.compare_digest(row.code_hash, security.hash_code(_secret(), email, code)):
            row.attempts += 1
            left = MAX_ATTEMPTS - row.attempts
            await db.commit()
            error = (f"Код не подошёл. Проверьте цифры в последнем письме — осталось попыток: {left}."
                     if left else "Код не подошёл. Запросите, пожалуйста, новый.")
            return _code_page(request, email, status=400, error=error)

        row.used_at = func.now()
        user_id = (await db.execute(
            insert(User).values(email=email, last_login_at=func.now())
            .on_conflict_do_update(index_elements=[User.email], set_={"last_login_at": func.now()})
            .returning(User.id)
        )).scalar_one()
        token = security.new_token()
        db.add(AuthSession(user_id=user_id, token_hash=security.hash_token(token),
                           user_agent=(request.headers.get("user-agent") or "")[:300],
                           expires_at=func.now() + timedelta(days=SESSION_DAYS)))
        await db.commit()

    resp = RedirectResponse("/today", status_code=303)
    _set_cookie(resp, SESSION_COOKIE, token, SESSION_DAYS * 24 * 3600)
    resp.delete_cookie(EMAIL_COOKIE, path="/")
    return resp


@router.post("/logout")
async def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        async with SessionLocal() as db:
            row = (await db.execute(
                select(AuthSession).where(AuthSession.token_hash == security.hash_token(token))
            )).scalar_one_or_none()
            if row:
                await db.delete(row)
                await db.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
