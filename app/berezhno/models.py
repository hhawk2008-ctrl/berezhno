from datetime import date, datetime, time

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, SmallInteger, String, Time, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    timezone: Mapped[str] = mapped_column(String, server_default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    name: Mapped[str | None] = mapped_column(String)
    morning_time: Mapped[time] = mapped_column(Time, server_default="08:30")
    evening_time: Mapped[time] = mapped_column(Time, server_default="21:30")
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_selfhelp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_pd_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crisis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginCode(Base):
    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String)
    code_hash: Mapped[str] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    user_agent: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    answers: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    main_risk: Mapped[str | None] = mapped_column(String)
    draft_plan: Mapped[dict | None] = mapped_column(JSONB)
    plan_source: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoalStage(Base):
    __tablename__ = "goal_stages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    minutes: Mapped[int] = mapped_column(Integer, server_default="15")
    if_then: Mapped[str | None] = mapped_column(String)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, server_default="planned")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    step_id: Mapped[int | None] = mapped_column(ForeignKey("steps.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DayEnergy(Base):
    __tablename__ = "day_energy"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[int] = mapped_column(SmallInteger)
