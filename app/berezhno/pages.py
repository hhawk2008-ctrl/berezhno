"""Экраны после входа: знакомство, постановка цели, «Сегодня», шаг на завтра, цель, копилка, помощь."""
import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from . import ai, safety
from .auth import current_user
from .db import SessionLocal
from .models import DayEnergy, Evidence, Goal, GoalStage, Step, User
from .thoughts import thought_for
from .web import templates

log = logging.getLogger(__name__)
router = APIRouter()

QUESTIONS = [
    ("done", "Как вы поймёте, что цель достигнута?"),
    ("deadline", "К какому сроку хотелось бы?"),
    ("time", "Сколько времени в неделю у вас реально есть на эту цель?"),
    ("obstacle", "Что мешало раньше, если вы уже пробовали?"),
]
EVENING_FROM_HOUR = 18  # после этого часа первый шаг переносится на завтра

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]


def ru_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


templates.env.filters["ru_date"] = ru_date


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def user_tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def local_now(user: User) -> datetime:
    return datetime.now(user_tz(user))


async def need_user(request: Request, *, onboarded: bool = True) -> tuple[User | None, Response | None]:
    user = await current_user(request)
    if user is None:
        return None, redirect("/login")
    if onboarded and user.onboarded_at is None:
        return None, redirect("/welcome")
    return user, None


async def get_goal(db, user: User, status: str) -> Goal | None:
    return (await db.execute(
        select(Goal).where(Goal.user_id == user.id, Goal.status == status).order_by(Goal.id.desc()).limit(1)
    )).scalar_one_or_none()


async def latest_step(db, goal: Goal) -> Step | None:
    return (await db.execute(
        select(Step).where(Step.goal_id == goal.id).order_by(Step.day.desc(), Step.id.desc()).limit(1)
    )).scalar_one_or_none()


def parse_time(value: str, default: time) -> time:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return default
    return time(int(match.group(1)), int(match.group(2)))


# ---------- Знакомство (A3) ----------

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_form(request: Request) -> Response:
    user, resp = await need_user(request, onboarded=False)
    if resp:
        return resp
    if user.onboarded_at:
        return redirect("/today")
    return templates.TemplateResponse(request, "welcome.html", {"user": user, "error": ""})


@router.post("/welcome")
async def welcome_save(request: Request, name: str = Form(""), morning: str = Form("08:30"),
                       evening: str = Form("21:30"), tz: str = Form(""), selfhelp: str = Form(""),
                       pd: str = Form("")) -> Response:
    user, resp = await need_user(request, onboarded=False)
    if resp:
        return resp
    if not selfhelp or not pd:
        return templates.TemplateResponse(request, "welcome.html", {
            "user": user, "error": "Чтобы продолжить, отметьте, пожалуйста, обе галочки внизу."}, status_code=400)
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        tz = "Europe/Moscow"
    async with SessionLocal() as db:
        db_user = await db.get(User, user.id)
        db_user.name = name.strip()[:60] or None
        db_user.morning_time = parse_time(morning, time(8, 30))
        db_user.evening_time = parse_time(evening, time(21, 30))
        db_user.timezone = tz
        db_user.consent_selfhelp_at = func.now()
        db_user.consent_pd_at = func.now()
        db_user.onboarded_at = func.now()
        await db.commit()
    return redirect("/goal/new")


# ---------- Постановка цели (A4) ----------

FORBIDDEN_TEXT = ("С такой целью «Бережно» пока не помогает: здесь важна поддержка специалиста, а не только "
                  "напоминания и маленькие шаги. Можно поставить другую цель или написать нам, и мы подскажем, "
                  "куда обратиться.")


async def _mark_crisis(user: User) -> None:
    async with SessionLocal() as db:
        db_user = await db.get(User, user.id)
        db_user.crisis_at = func.now()
        await db.commit()
    log.warning("Кризисный сигнал у пользователя %s", user.id)


@router.get("/goal/new", response_class=HTMLResponse)
async def goal_new_form(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        if await get_goal(db, user, "active"):
            return redirect("/today")
        draft = await get_goal(db, user, "draft")
    return templates.TemplateResponse(request, "goal_new.html", {
        "title": draft.title if draft else "", "error": "", "forbidden": ""})


@router.post("/goal/new")
async def goal_new_save(request: Request, title: str = Form("")) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    title = " ".join(title.split())[:300]
    if len(title) < 3:
        return templates.TemplateResponse(request, "goal_new.html", {
            "title": title, "forbidden": "", "error": "Напишите цель хотя бы парой слов — так будет проще помочь."},
            status_code=400)
    verdict = safety.classify(title)
    if verdict == "crisis":
        await _mark_crisis(user)
        return redirect("/help-now")
    if verdict == "forbidden":
        return templates.TemplateResponse(request, "goal_new.html", {
            "title": title, "error": "", "forbidden": FORBIDDEN_TEXT})
    async with SessionLocal() as db:
        if await get_goal(db, user, "active"):
            return redirect("/today")
        draft = await get_goal(db, user, "draft")
        if draft is None:
            draft = Goal(user_id=user.id, title=title, answers={})
            db.add(draft)
        else:
            draft.title = title
        await db.commit()
    return redirect("/goal/new/questions")


@router.get("/goal/new/questions", response_class=HTMLResponse)
async def questions_form(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        draft = await get_goal(db, user, "draft")
    if draft is None:
        return redirect("/goal/new")
    return templates.TemplateResponse(request, "goal_questions.html", {
        "goal": draft, "questions": QUESTIONS, "answers": draft.answers or {}})


@router.post("/goal/new/questions")
async def questions_save(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    form = await request.form()
    answers = {key: " ".join(str(form.get(key, "")).split())[:500] for key, _ in QUESTIONS}
    async with SessionLocal() as db:
        draft = await get_goal(db, user, "draft")
        if draft is None:
            return redirect("/goal/new")
        verdict = safety.classify(" ".join([draft.title, *answers.values()]))
        if verdict == "crisis":
            await _mark_crisis(user)
            return redirect("/help-now")
        if verdict == "forbidden":
            return templates.TemplateResponse(request, "goal_new.html", {
                "title": draft.title, "error": "", "forbidden": FORBIDDEN_TEXT})
        draft.answers = answers
        draft.main_risk = answers.get("obstacle") or None
        await db.commit()
        return await _plan_and_go(request, user, draft.id)


async def _plan_and_go(request: Request, user: User, draft_id: int) -> Response:
    async with SessionLocal() as db:
        draft = await db.get(Goal, draft_id)
        answers = {text: (draft.answers or {}).get(key, "") for key, text in QUESTIONS}
        try:
            plan = await ai.make_plan(draft.title, answers)
        except ai.AIError:
            plan = None
        if plan and plan["topic"] == "crisis":
            await _mark_crisis(user)
            return redirect("/help-now")
        if plan and plan["topic"] == "forbidden":
            return templates.TemplateResponse(request, "goal_new.html", {
                "title": draft.title, "error": "", "forbidden": FORBIDDEN_TEXT})
        draft.draft_plan = plan or {"stages": [], "first_step": {"title": "", "minutes": 15}, "if_then": ""}
        draft.plan_source = "ai" if plan else "manual"
        await db.commit()
    return redirect("/goal/new/plan")


@router.post("/goal/new/replan")
async def replan(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        draft = await get_goal(db, user, "draft")
    if draft is None:
        return redirect("/goal/new")
    return await _plan_and_go(request, user, draft.id)


@router.get("/goal/new/plan", response_class=HTMLResponse)
async def plan_form(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        draft = await get_goal(db, user, "draft")
    if draft is None or draft.draft_plan is None:
        return redirect("/goal/new")
    plan = draft.draft_plan
    stages = (plan.get("stages") or []) + [""] * 5
    return templates.TemplateResponse(request, "goal_plan.html", {
        "goal": draft, "stages": stages[:5], "step": plan.get("first_step") or {}, "if_then": plan.get("if_then", ""),
        "manual": draft.plan_source == "manual", "error": ""})


@router.post("/goal/new/plan")
async def plan_save(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    form = await request.form()
    stages = [" ".join(str(form.get(f"stage{i}", "")).split())[:200] for i in range(5)]
    stages = [s for s in stages if s]
    step_title = " ".join(str(form.get("step_title", "")).split())[:200]
    if_then = " ".join(str(form.get("if_then", "")).split())[:300]
    try:
        minutes = max(5, min(int(str(form.get("step_minutes", "15"))), 120))
    except ValueError:
        minutes = 15
    async with SessionLocal() as db:
        draft = await get_goal(db, user, "draft")
        if draft is None:
            return redirect("/goal/new")
        if not stages or not step_title:
            return templates.TemplateResponse(request, "goal_plan.html", {
                "goal": draft, "stages": (stages + [""] * 5)[:5],
                "step": {"title": step_title, "minutes": minutes}, "if_then": if_then,
                "manual": draft.plan_source == "manual",
                "error": "Нужен хотя бы один этап и первый шаг — с них всё и начнётся."}, status_code=400)
        for pos, title in enumerate(stages, start=1):
            db.add(GoalStage(goal_id=draft.id, position=pos, title=title))
        now = local_now(user)
        first_day = now.date() + timedelta(days=1) if now.hour >= EVENING_FROM_HOUR else now.date()
        db.add(Step(user_id=user.id, goal_id=draft.id, title=step_title, minutes=minutes,
                    if_then=if_then or None, day=first_day))
        draft.status = "active"
        await db.commit()
    return redirect("/start")


@router.get("/start", response_class=HTMLResponse)
async def start(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        goal = await get_goal(db, user, "active")
        if goal is None:
            return redirect("/goal/new")
        step = await latest_step(db, goal)
    return templates.TemplateResponse(request, "start.html", {
        "user": user, "step": step, "is_today": step is not None and step.day == local_now(user).date()})


# ---------- Сегодня (B1, B2) ----------

RESULTS = {"done", "partial", "not_done"}


@router.get("/today", response_class=HTMLResponse)
async def today(request: Request, r: str = "") -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    today_ = local_now(user).date()
    async with SessionLocal() as db:
        goal = await get_goal(db, user, "active")
        if goal is None:
            return redirect("/goal/new")
        step = await latest_step(db, goal)
        energy = await db.get(DayEnergy, (user.id, today_))
        week_days = (await db.execute(
            select(func.count(func.distinct(Step.day))).where(
                Step.user_id == user.id, Step.status.in_(["done", "partial"]), Step.day > today_ - timedelta(days=7))
        )).scalar_one()
        week_steps = (await db.execute(
            select(func.count()).where(
                Step.user_id == user.id, Step.status.in_(["done", "partial"]), Step.day > today_ - timedelta(days=7))
        )).scalar_one()
        total_steps = (await db.execute(
            select(func.count()).where(Step.user_id == user.id, Step.status.in_(["done", "partial"]))
        )).scalar_one()

    if step is None:
        state = "need_step"
    elif step.status == "planned":
        state = "upcoming" if step.day > today_ else ("planned" if step.day == today_ else "overdue")
    else:
        state = "checked" if step.day >= today_ else "need_step"

    return templates.TemplateResponse(request, "today.html", {
        "user": user, "goal": goal, "step": step, "state": state, "today": today_,
        "thought": thought_for(user.id, today_), "energy": energy.value if energy else None,
        "result": r if r in RESULTS else "", "week_days": week_days, "week_steps": week_steps,
        "total_steps": total_steps,
    })


@router.post("/today/checkin")
async def checkin(request: Request, step_id: int = Form(...), result: str = Form(...)) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    if result not in RESULTS:
        return redirect("/today")
    today_ = local_now(user).date()
    async with SessionLocal() as db:
        step = await db.get(Step, step_id)
        if step is None or step.user_id != user.id or step.status != "planned" or step.day > today_:
            return redirect("/today")
        step.status = result
        step.checked_at = func.now()
        if result in {"done", "partial"}:
            db.add(Evidence(user_id=user.id, step_id=step.id, kind=f"step_{result}",
                            text=step.title if result == "done" else f"{step.title} (частично)"))
        await db.commit()
    return redirect(f"/today?r={result}")


@router.post("/today/energy")
async def set_energy(request: Request, value: int = Form(...)) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    if 1 <= value <= 5:
        async with SessionLocal() as db:
            await db.execute(insert(DayEnergy).values(user_id=user.id, day=local_now(user).date(), value=value)
                             .on_conflict_do_update(index_elements=["user_id", "day"], set_={"value": value}))
            await db.commit()
    return redirect("/today")


# ---------- Шаг на завтра (B4) ----------

async def _next_target(db, user: User, goal: Goal) -> tuple[Step | None, Step | None, date]:
    """(шаг, который правим, если он уже запланирован; последний шаг для подсказки; день нового шага)."""
    today_ = local_now(user).date()
    last = await latest_step(db, goal)
    if last and last.status == "planned" and last.day >= today_:
        return last, last, last.day
    day = today_ if (last is None or last.day < today_) else today_ + timedelta(days=1)
    return None, last, day


@router.get("/step/next", response_class=HTMLResponse)
async def next_step_form(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        goal = await get_goal(db, user, "active")
        if goal is None:
            return redirect("/goal/new")
        editing, last, day = await _next_target(db, user, goal)
    suggest_half = bool(last and last.status == "not_done")
    minutes = last.minutes if last else 15
    if suggest_half and not editing:
        minutes = max(5, minutes // 2)
    return templates.TemplateResponse(request, "step_next.html", {
        "goal": goal, "editing": editing, "last": last, "day": day, "is_today": day == local_now(user).date(),
        "title": last.title if last else "", "minutes": minutes, "if_then": (last.if_then or "") if last else "",
        "suggest_half": suggest_half and not editing})


@router.post("/step/next")
async def next_step_save(request: Request, title: str = Form(""), minutes: str = Form("15"),
                         if_then: str = Form(""), action: str = Form("save")) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    title = " ".join(title.split())[:200]
    if_then = " ".join(if_then.split())[:300]
    try:
        mins = max(5, min(int(minutes), 120))
    except ValueError:
        mins = 15
    if action == "half":
        mins = max(5, mins // 2)
    async with SessionLocal() as db:
        goal = await get_goal(db, user, "active")
        if goal is None:
            return redirect("/goal/new")
        editing, _, day = await _next_target(db, user, goal)
        if not title:
            return redirect("/step/next")
        if editing:
            editing.title, editing.minutes, editing.if_then = title, mins, if_then or None
        else:
            db.add(Step(user_id=user.id, goal_id=goal.id, title=title, minutes=mins, if_then=if_then or None, day=day))
        await db.commit()
    return redirect("/today")


# ---------- Цель, копилка, помощь ----------

@router.get("/goal", response_class=HTMLResponse)
async def goal_page(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        goal = await get_goal(db, user, "active")
        if goal is None:
            return redirect("/goal/new")
        stages = (await db.execute(
            select(GoalStage).where(GoalStage.goal_id == goal.id).order_by(GoalStage.position))).scalars().all()
    answers = goal.answers or {}
    return templates.TemplateResponse(request, "goal.html", {
        "goal": goal, "stages": stages,
        "answers": [(text, answers.get(key)) for key, text in QUESTIONS if answers.get(key)]})


@router.get("/evidence", response_class=HTMLResponse)
async def evidence_page(request: Request) -> Response:
    user, resp = await need_user(request)
    if resp:
        return resp
    async with SessionLocal() as db:
        items = (await db.execute(
            select(Evidence).where(Evidence.user_id == user.id).order_by(Evidence.created_at.desc()).limit(200)
        )).scalars().all()
    tz = user_tz(user)
    return templates.TemplateResponse(request, "evidence.html", {
        "items": [(i, i.created_at.astimezone(tz).date()) for i in items]})


@router.get("/help-now", response_class=HTMLResponse)
async def help_now(request: Request) -> Response:
    user = await current_user(request)
    return templates.TemplateResponse(request, "help_now.html", {"user": user})


@router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy(request: Request) -> Response:
    return templates.TemplateResponse(request, "privacy_policy.html", {})
