import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc

from app.config import settings
from app.db.session import SessionLocal
from app.models import (
    Employee, TelegramUser, UserRole, Shift, InventoryBalance, Product,
    SalaryViolation, SalaryPeriod, NonMonetaryBonus, Guest, GuestTelegram,
    OwnerReportSettings, AuditLog, Club
)
from app.services.langame import langame_client, LangameAPIError

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Strike Arena Telegram Mini App", version="1.29.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(401, "Telegram initData is required")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Invalid Telegram initData")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise HTTPException(401, "Invalid auth_date")
    if not auth_date or abs(time.time() - auth_date) > 86400:
        raise HTTPException(401, "Expired Telegram initData")
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(
        b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
    ).digest()
    calculated = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Invalid Telegram initData signature")
    return pairs


async def current_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    pairs = validate_init_data(init_data)
    try:
        raw_user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(401, "Invalid Telegram user data")
    telegram_id = raw_user.get("id")
    if not telegram_id:
        raise HTTPException(401, "Telegram user is missing")
    async with SessionLocal() as session:
        user = (
            await session.execute(
                select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
            )
        ).scalar_one_or_none()
        if not user or not user.active:
            raise HTTPException(403, "Access is not configured")
        return user, raw_user


def owner_required(user):
    if user.role != UserRole.OWNER.value:
        raise HTTPException(403, "OWNER access required")


def dec(v):
    return float(v or 0)


def iso(v):
    return v.isoformat() if v else None


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "strike-arena-mini-app", "version": "1.29.0"}


@app.get("/api/me")
async def me(request: Request):
    user, tg = await current_user(request)
    async with SessionLocal() as session:
        employee = None
        if user.employee_id:
            employee = await session.get(Employee, user.employee_id)
        return {
            "telegram_id": user.telegram_id,
            "role": user.role,
            "display_name": employee.full_name if employee and employee.full_name else tg.get("first_name", "Пользователь"),
            "username": tg.get("username"),
            "employee_id": user.employee_id,
        }


@app.get("/api/summary")
async def summary(request: Request):
    user, _ = await current_user(request)
    async with SessionLocal() as session:
        employees = await session.scalar(select(func.count(Employee.id)).where(Employee.active.is_(True)))
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None)))
        violations = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.created_at >= datetime.now(timezone.utc) - timedelta(days=30)))
        critical = await session.scalar(
            select(func.count(InventoryBalance.id)).where(
                InventoryBalance.min_stock > 0,
                InventoryBalance.quantity <= InventoryBalance.min_stock,
            )
        )
        return {
            "role": user.role,
            "employees": employees or 0,
            "open_shifts": open_shifts or 0,
            "violations_30d": violations or 0,
            "critical_stock": critical or 0,
        }


@app.get("/api/dashboard")
async def dashboard(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from app.bot.analytics import sales_totals
    sales, units, _ = await sales_totals(start, now)
    async with SessionLocal() as session:
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None)))
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(
            InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock
        ))
        pending = await session.scalar(select(func.count(SalaryViolation.id)).where(
            SalaryViolation.dismissal_required.is_(True)
        ))
        return {"sales": dec(sales), "units": dec(units), "open_shifts": open_shifts or 0,
                "critical_stock": critical or 0, "dismissal_required": pending or 0}


@app.get("/api/admins")
async def admins(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Employee, TelegramUser)
            .outerjoin(TelegramUser, TelegramUser.employee_id == Employee.id)
            .where(Employee.active.is_(True))
            .order_by(Employee.full_name)
        )).all()
        return {"items": [{
            "id": e.id, "name": e.full_name or f"Сотрудник #{e.id}",
            "phone": e.phone, "telegram_id": tu.telegram_id if tu else None,
            "role": tu.role if tu else "not_linked", "access_active": bool(tu and tu.active),
            "langame_user_id": e.langame_user_id
        } for e, tu in rows]}


@app.get("/api/clients")
async def clients(request: Request, q: str = "", limit: int = 30):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    try:
        data = await langame_client.guests_search(query=q or None, size=min(max(limit, 1), 100))
        return {"source": "langame", "data": data}
    except LangameAPIError as exc:
        # Fallback to locally synchronized guests.
        async with SessionLocal() as session:
            stmt = select(Guest).order_by(desc(Guest.updated_at)).limit(min(max(limit, 1), 100))
            if q:
                stmt = stmt.where((Guest.fio.ilike(f"%{q}%")) | (Guest.phone.ilike(f"%{q}%")))
            rows = (await session.execute(stmt)).scalars().all()
            return {"source": "local_fallback", "error": str(exc), "items": [
                {"id": g.id, "langame_guest_id": g.langame_guest_id, "fio": g.fio, "phone": g.phone}
                for g in rows
            ]}


@app.get("/api/inventory")
async def inventory(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(InventoryBalance, Product, Club)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Club, Club.id == InventoryBalance.club_id)
            .order_by(InventoryBalance.quantity.asc())
            .limit(100)
        )).all()
        return {"items": [{
            "id": b.id, "club": c.name, "product": p.name,
            "quantity": dec(b.quantity), "min_stock": dec(b.min_stock),
            "critical": bool(b.min_stock > 0 and b.quantity <= b.min_stock),
            "updated_at": iso(b.updated_at)
        } for b, p, c in rows]}


@app.get("/api/finance")
async def finance(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 90)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    from app.bot.analytics import sales_totals
    sales, units, _ = await sales_totals(start, end)
    async with SessionLocal() as session:
        salaries = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(
            SalaryPeriod.date_from >= start.date(), SalaryPeriod.date_to <= end.date()
        ))
        penalties = await session.scalar(select(func.coalesce(func.sum(SalaryViolation.amount), 0)).where(
            SalaryViolation.created_at >= start, SalaryViolation.created_at <= end
        ))
        return {"days": days, "sales": dec(sales), "units": dec(units),
                "salary": dec(salaries), "penalties": dec(penalties),
                "net_before_other": dec(sales) - dec(salaries) - dec(penalties)}


@app.get("/api/analytics")
async def analytics(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 90)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    from app.bot.analytics import sales_rows, admins_ranking
    rows = await sales_rows(start, end)
    ranking = await admins_ranking(days)
    return {"days": days, "sales_rows": rows, "ranking": ranking}


@app.get("/api/penalties")
async def penalties(request: Request, limit: int = 50):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(SalaryViolation, Employee)
            .join(Employee, Employee.id == SalaryViolation.employee_id)
            .order_by(SalaryViolation.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )).all()
        return {"items": [{
            "id": v.id, "employee_id": e.id, "employee": e.full_name or str(e.id),
            "rule": v.rule_code, "title": v.title, "amount": dec(v.amount),
            "premium_reduction_percent": dec(v.premium_reduction_percent),
            "dismissal_required": v.dismissal_required, "comment": v.comment,
            "created_at": iso(v.created_at)
        } for v, e in rows]}


@app.get("/api/bonuses")
async def bonuses(request: Request, limit: int = 50):
    user, _ = await current_user(request)
    async with SessionLocal() as session:
        stmt = select(NonMonetaryBonus, Employee).join(
            Employee, Employee.id == NonMonetaryBonus.employee_id
        ).order_by(NonMonetaryBonus.created_at.desc()).limit(min(max(limit, 1), 100))
        if user.role == UserRole.ADMIN.value:
            if not user.employee_id:
                return {"items": []}
            stmt = stmt.where(NonMonetaryBonus.employee_id == user.employee_id)
        elif user.role != UserRole.OWNER.value:
            raise HTTPException(403, "Access denied")
        rows = (await session.execute(stmt)).all()
        return {"items": [{
            "id": b.id, "employee": e.full_name or str(e.id), "title": b.title,
            "type": b.bonus_type, "comment": b.comment, "created_at": iso(b.created_at)
        } for b, e in rows]}


@app.get("/api/my-stats")
async def my_stats(request: Request):
    user, _ = await current_user(request)
    if user.role != UserRole.ADMIN.value or not user.employee_id:
        raise HTTPException(403, "ADMIN access required")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    async with SessionLocal() as session:
        shifts = await session.scalar(select(func.count(Shift.id)).where(
            Shift.employee_id == user.employee_id, Shift.started_at >= start
        ))
        open_shift = await session.scalar(select(func.count(Shift.id)).where(
            Shift.employee_id == user.employee_id, Shift.ended_at.is_(None)
        ))
        violations = await session.scalar(select(func.coalesce(func.sum(SalaryViolation.amount), 0)).where(
            SalaryViolation.employee_id == user.employee_id, SalaryViolation.created_at >= start
        ))
        return {"shifts_30d": shifts or 0, "open_shift": open_shift or 0, "penalties": dec(violations)}


@app.get("/api/my-salary")
async def my_salary(request: Request):
    user, _ = await current_user(request)
    if user.role != UserRole.ADMIN.value or not user.employee_id:
        raise HTTPException(403, "ADMIN access required")
    async with SessionLocal() as session:
        periods = (await session.execute(
            select(SalaryPeriod).where(SalaryPeriod.employee_id == user.employee_id)
            .order_by(SalaryPeriod.date_to.desc()).limit(20)
        )).scalars().all()
        return {"items": [{
            "id": p.id, "from": p.date_from.isoformat(), "to": p.date_to.isoformat(),
            "base": dec(p.base_amount), "bonus": dec(p.bonus_amount),
            "total": dec(p.total_amount), "status": p.status
        } for p in periods]}


@app.get("/api/shifts")
async def shifts(request: Request, days: int = 30):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Access denied")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=min(max(days, 1), 90))
    async with SessionLocal() as session:
        stmt = select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(
            Shift.started_at >= start
        ).order_by(Shift.started_at.desc()).limit(100)
        if user.role == UserRole.ADMIN.value and user.employee_id:
            stmt = stmt.where(Shift.employee_id == user.employee_id)
        rows = (await session.execute(stmt)).all()
        return {"items": [{
            "id": s.id, "employee": e.full_name if e else str(s.employee_id),
            "started_at": iso(s.started_at), "ended_at": iso(s.ended_at),
            "status": "open" if s.ended_at is None else "closed"
        } for s, e in rows]}


@app.get("/api/attention")
async def attention(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(
            InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock
        ))
        pending_dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(
            SalaryViolation.dismissal_required.is_(True)
        ))
        return {"critical_stock": critical or 0, "dismissal_required": pending_dismissals or 0}


@app.get("/api/settings")
async def owner_settings(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        cfg = await session.scalar(select(OwnerReportSettings).where(
            OwnerReportSettings.owner_telegram_id == user.telegram_id
        ))
        if not cfg:
            return {"configured": False}
        return {
            "configured": True, "enabled": cfg.enabled, "timezone": cfg.report_timezone,
            "hour": cfg.report_hour, "minute": cfg.report_minute,
            "include_sales": cfg.include_sales, "include_shifts": cfg.include_shifts,
            "include_inventory": cfg.include_inventory, "include_discrepancies": cfg.include_discrepancies,
            "include_salary": cfg.include_salary, "include_clients": cfg.include_clients,
            "send_excel": cfg.send_excel
        }


class PenaltyRequest(BaseModel):
    employee_id: int
    code: str
    comment: str = Field(default="", max_length=4000)


@app.post("/api/penalties")
async def create_penalty(request: Request, payload: PenaltyRequest):
    user, _ = await current_user(request)
    owner_required(user)
    from app.bot.penalties import RULE_MAP, create_manual_penalty
    if payload.code not in RULE_MAP:
        raise HTTPException(400, "Unknown penalty rule")
    try:
        await create_manual_penalty(user.telegram_id, payload.employee_id, payload.code, payload.comment)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/api/penalty-rules")
async def penalty_rules(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    from app.bot.penalties import RULE_MAP
    return {"items": [{
        "code": code, "title": data[1], "amount": dec(data[2]),
        "repeat": bool(data[3]), "premium": bool(data[4])
    } for code, data in RULE_MAP.items()]}


@app.get("/api/audit")
async def audit(request: Request, limit: int = 100):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 200))
        )).scalars().all()
        return {"items": [{
            "id": x.id, "action": x.action, "entity_type": x.entity_type,
            "entity_id": x.entity_id, "created_at": iso(x.created_at),
            "payload": x.payload
        } for x in rows]}
