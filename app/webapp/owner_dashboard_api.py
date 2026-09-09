from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import SalaryPeriod, SalaryViolation, Shift
from app.services.timezone_policy import local_day_bounds, timezone_name
from app.webapp.app import current_user
from app.webapp.unified_api import product_sales_totals

router = APIRouter(prefix="/api/app", tags=["owner-dashboard"])


def money(value):
    return float(Decimal(str(value or 0)))


@router.get("/overview")
async def owner_overview(request: Request):
    user, _ = await current_user(request)
    # SMM gets a marketing-only home response. It must never receive owner finance/operations data.
    if user.role == "smm":
        from app.webapp.smm_api import smm_analytics
        analytics = await smm_analytics(request, days=30)
        return {
            "role": "smm",
            "timezone": timezone_name(),
            "revenue": {},
            "payments": {},
            "kpi": {"guests": analytics.get("guests"), "new_guests": None, "average_check": None, "open_shifts": None},
            "marketing": {"campaigns": analytics.get("campaigns"), "tasks": analytics.get("tasks"), "approved_tasks": analytics.get("approved_tasks")},
            "source_status": {"langame": "ok"},
        }
    if user.role != "owner":
        raise HTTPException(403, "Owner dashboard is restricted to OWNER")
    start, end = local_day_bounds()
    async with SessionLocal() as session:
        cash = await session.scalar(select(func.coalesce(func.sum(Shift.cash_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        card = await session.scalar(select(func.coalesce(func.sum(Shift.card_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        mobile = await session.scalar(select(func.coalesce(func.sum(Shift.mobile_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
    products, units = await product_sales_totals(start, end)
    till = money(cash) + money(card) + money(mobile)
    return {
        "role": user.role,
        "timezone": timezone_name(),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "revenue": {"till": till, "products": products, "total": till, "gaming": None, "other": None, "product_units": units},
        "payments": {"cash": money(cash), "card": money(card), "mobile": money(mobile)},
        "kpi": {"guests": None, "new_guests": None, "average_check": None, "open_shifts": int(open_shifts)},
        "source_status": {"langame": "ok"},
        "notes": ["Касса и продажи товаров разделены.", "Неподтверждённые gaming/прочие доходы не подменяются нулём."],
    }


@router.get("/finance")
async def finance_dashboard(request: Request, days: int = 30):
    user, _ = await current_user(request)
    if user.role != "owner":
        raise HTTPException(403, "Finance dashboard is restricted to OWNER")
    days = min(max(days, 1), 365)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    async with SessionLocal() as session:
        cash = await session.scalar(select(func.coalesce(func.sum(Shift.cash_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        card = await session.scalar(select(func.coalesce(func.sum(Shift.card_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        mobile = await session.scalar(select(func.coalesce(func.sum(Shift.mobile_sales), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        difference = await session.scalar(select(func.coalesce(func.sum(Shift.cash_difference), 0)).where(Shift.started_at >= start, Shift.started_at <= end)) or 0
        salary = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from <= end.date(), SalaryPeriod.date_to >= start.date())) or 0
        penalties = await session.scalar(select(func.coalesce(func.sum(SalaryViolation.amount), 0)).where(SalaryViolation.created_at >= start, SalaryViolation.created_at <= end)) or 0
    products, units = await product_sales_totals(start, end)
    till = money(cash) + money(card) + money(mobile)
    return {
        "role": user.role,
        "days": days,
        "timezone": timezone_name(),
        "cashflow": {"cash": money(cash), "card": money(card), "mobile": money(mobile), "total": till, "cash_difference": money(difference)},
        "products": {"revenue": products, "units": units, "cogs": None, "profit": None, "margin": None},
        "expenses": {"salary": money(salary), "penalties": money(penalties)},
        "net_before_other": till - money(salary) - money(penalties),
        "source_note": "Касса — локальные смены; продажи товаров — LANGAME. COGS и gaming показываются только после подтверждения источника.",
    }
