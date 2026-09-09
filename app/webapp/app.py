import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc

from app.config import settings
from app.db.session import SessionLocal
from app.models import (
    Employee, TelegramUser, UserRole, Shift, InventoryBalance, Product,
    SalaryViolation, SalaryPeriod, NonMonetaryBonus, Guest, GuestTelegram,
    OwnerReportSettings, AuditLog, Club, AccessProfile
)
from app.services.langame import langame_client, LangameAPIError

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
EXPORT_DIR = BASE_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Strike Arena Telegram Mini App", version="1.30.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def validate_init_data(init_data: str) -> dict:
    if not init_data: raise HTTPException(401, "Telegram initData is required")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True)); received_hash = pairs.pop("hash", None)
    if not received_hash: raise HTTPException(401, "Invalid Telegram initData")
    try: auth_date = int(pairs.get("auth_date", "0"))
    except ValueError: raise HTTPException(401, "Invalid auth_date")
    if not auth_date or abs(time.time() - auth_date) > 86400: raise HTTPException(401, "Expired Telegram initData")
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash): raise HTTPException(401, "Invalid Telegram initData signature")
    return pairs


async def current_user(request: Request):
    pairs = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    try: raw_user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError: raise HTTPException(401, "Invalid Telegram user data")
    telegram_id = raw_user.get("id")
    if not telegram_id: raise HTTPException(401, "Telegram user is missing")
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))).scalar_one_or_none()
        if user and user.active:
            return user, raw_user
        username = str(raw_user.get("username") or "").lower().replace("@", "").strip()
        if username:
            profile = (await session.execute(select(AccessProfile).where(AccessProfile.username == username, AccessProfile.active.is_(True), AccessProfile.role == UserRole.OWNER.value))).scalar_one_or_none()
            if profile:
                if user is None:
                    user = TelegramUser(telegram_id=telegram_id, role=UserRole.OWNER.value, active=True)
                    session.add(user)
                else:
                    user.role = UserRole.OWNER.value
                    user.active = True
                await session.commit()
                return user, raw_user
        # Every Telegram account can enter the public guest contour without staff binding.
        return SimpleNamespace(telegram_id=telegram_id, role="guest", active=True, employee_id=None), raw_user


def owner_required(user):
    if user.role != UserRole.OWNER.value: raise HTTPException(403, "OWNER access required")

def dec(v): return float(v or 0)
def iso(v): return v.isoformat() if v else None

@app.get("/")
async def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    asset_tags = '<script src="/static/auth-v2.js?v=1"></script><link rel="stylesheet" href="/static/design-v2.css?v=1"><script src="/static/design-v2.js?v=1"></script>'
    html = html.replace("</head>", asset_tags + "</head>")
    response = HTMLResponse(html)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

@app.get("/healthz")
async def healthz(): return {"ok": True, "service": "strike-arena-mini-app", "version": "1.30.0"}

@app.get("/api/me")
async def me(request: Request):
    user, tg = await current_user(request)
    async with SessionLocal() as session:
        employee = await session.get(Employee, user.employee_id) if user.employee_id else None
        return {"telegram_id": user.telegram_id, "role": user.role, "display_name": employee.full_name if employee and employee.full_name else tg.get("first_name", "Пользователь"), "username": tg.get("username"), "employee_id": user.employee_id}

@app.get("/api/summary")
async def summary(request: Request):
    user, _ = await current_user(request)
    async with SessionLocal() as session:
        employees = await session.scalar(select(func.count(Employee.id)).where(Employee.active.is_(True)))
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None)))
        violations = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.created_at >= datetime.now(timezone.utc) - timedelta(days=30)))
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock))
        return {"role": user.role, "employees": employees or 0, "open_shifts": open_shifts or 0, "violations_30d": violations or 0, "critical_stock": critical or 0}

@app.get("/api/dashboard")
async def dashboard(request: Request):
    user, _ = await current_user(request); owner_required(user)
    now = datetime.now(timezone.utc); start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from app.bot.analytics import sales_totals
    sales, units, _ = await sales_totals(start, now)
    async with SessionLocal() as session:
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None)))
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock))
        pending = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True)))
        return {"sales": dec(sales), "units": dec(units), "open_shifts": open_shifts or 0, "critical_stock": critical or 0, "dismissal_required": pending or 0}

@app.get("/api/admins")
async def admins(request: Request):
    user, _ = await current_user(request); owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Employee, TelegramUser).outerjoin(TelegramUser, TelegramUser.employee_id == Employee.id).where(Employee.active.is_(True)).order_by(Employee.full_name))).all()
        return {"items": [{"id": e.id, "name": e.full_name or f"Сотрудник #{e.id}", "phone": e.phone, "telegram_id": tu.telegram_id if tu else None, "role": tu.role if tu else "not_linked", "access_active": bool(tu and tu.active), "langame_user_id": e.langame_user_id} for e, tu in rows]}

@app.get("/api/clients")
async def clients(request: Request, q: str = "", limit: int = 30):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value): raise HTTPException(403, "Access denied")
    try: return {"source": "langame", "data": await langame_client.guests_search(query=q or None, size=min(max(limit, 1), 100))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME clients unavailable: {exc}") from exc

@app.get("/api/inventory")
async def inventory(request: Request):
    user, _ = await current_user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value): raise HTTPException(403, "Access denied")
    async with SessionLocal() as session:
        rows = (await session.execute(select(InventoryBalance, Product, Club).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id).order_by(InventoryBalance.quantity.asc()).limit(100))).all()
        return {"items": [{"id": b.id, "club": c.name, "product": p.name, "quantity": dec(b.quantity), "min_stock": dec(b.min_stock), "critical": bool(b.min_stock > 0 and b.quantity <= b.min_stock), "updated_at": iso(b.updated_at)} for b,p,c in rows]}

@app.get("/api/bar-finance")
async def bar_finance(request: Request, days: int = 30):
    user, _ = await current_user(request); owner_required(user); days = min(max(days, 1), 3650)
    end = datetime.now(timezone.utc); start = end.replace(hour=0, minute=0, second=0, microsecond=0) if days == 1 else end - timedelta(days=days)
    from app.webapp.bar_finance import report
    try:
        bar = await report(start, end)
        return {"bar": bar, **bar}
    except LangameAPIError as exc: raise HTTPException(502, f"LANGAME bar finance unavailable: {exc}") from exc

@app.get("/api/finance")
async def finance(request: Request, days: int = 30):
    user, _ = await current_user(request); owner_required(user); days = min(max(days, 1), 90)
    end = datetime.now(timezone.utc); start = end - timedelta(days=days)
    from app.bot.analytics import sales_totals
    sales, units, _ = await sales_totals(start, end)
    async with SessionLocal() as session:
        salaries = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from >= start.date(), SalaryPeriod.date_to <= end.date()))
        penalties = await session.scalar(select(func.coalesce(func.sum(SalaryViolation.amount), 0)).where(SalaryViolation.created_at >= start, SalaryViolation.created_at <= end))
    return {"days": days, "sales": dec(sales), "units": dec(units), "salary": dec(salaries), "penalties": dec(penalties), "net_before_other": dec(sales)-dec(salaries)-dec(penalties)}

@app.get("/api/analytics")
async def analytics(request: Request, days: int = 30):
    user, _ = await current_user(request); owner_required(user); days = min(max(days, 1), 90)
    end = datetime.now(timezone.utc); start = end - timedelta(days=days)
    from app.bot.analytics import sales_rows, admins_ranking
    return {"days":days, "sales_rows":await sales_rows(start,end), "ranking":await admins_ranking(days)}

@app.get("/api/statistics")
async def statistics(request: Request, days: int | None = 30):
    user, _ = await current_user(request); owner_required(user)
    end = datetime.now(timezone.utc); start = datetime(2000,1,1,tzinfo=timezone.utc) if days is None or days <= 0 else end-timedelta(days=min(max(days,1),3650))
    from app.bot.analytics import sales_rows, admins_ranking
    rows=await sales_rows(start,end); ranking=await admins_ranking(None if days is None or days <= 0 else days)
    return {"from":iso(start),"to":iso(end),"sales_rows":rows,"admin_ranking":ranking}

@app.get("/api/statistics/export")
async def statistics_export(request: Request, days: int | None = 30):
    user, _ = await current_user(request); owner_required(user)
    from app.services.export import export_service
    from app.services.timezone_policy import timezone_name
    data=await statistics(request,days); rows=data["sales_rows"]; headers=sorted({k for row in rows for k in row}) if rows else ["empty"]
    path=export_service.build_xlsx("statistics",headers,rows,filters={"days":days},totals={"rows":len(rows)},timezone_name=timezone_name())
    return FileResponse(path,filename="statistics.xlsx",media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
