from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, select

from app.db.session import SessionLocal
from app.models import BonusRecord, Employee, UserRole
from app.services.cleaning_bonus import cleaning_bonus_status, materialize_monthly_cleaning_bonus, MOSCOW_TZ
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["bonuses"])


async def _user(request: Request):
    return (await current_user(request))[0]


def _month_now() -> tuple[int, int]:
    now = datetime.now(MOSCOW_TZ)
    return now.year, now.month


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


@router.get("/bonuses")
async def bonuses(request: Request):
    user = await _user(request)
    if user.role not in (UserRole.OWNER.value, UserRole.ADMIN.value):
        raise HTTPException(403, "Недостаточно прав")
    if user.role == UserRole.ADMIN.value and user.employee_id is None:
        raise HTTPException(403, "Нет привязанного администратора")

    year, month = _month_now()
    prev_year, prev_month = _previous_month(year, month)
    async with SessionLocal() as session:
        created = skipped = 0
        if user.role == UserRole.OWNER.value:
            created, skipped, _ = await materialize_monthly_cleaning_bonus(session, prev_year, prev_month)
            await session.commit()
        status = await cleaning_bonus_status(session, year, month)
        query = select(BonusRecord).order_by(desc(BonusRecord.created_at), desc(BonusRecord.id)).limit(300)
        if user.role == UserRole.ADMIN.value:
            query = query.where(BonusRecord.employee_id == user.employee_id)
        records = (await session.execute(query)).scalars().all()
        names = {}
        if user.role == UserRole.OWNER.value:
            ids = [r.employee_id for r in records]
            employees = (await session.execute(select(Employee).where(Employee.id.in_(ids)))).scalars().all() if ids else []
            names = {e.id: e.full_name or f"Администратор #{e.id}" for e in employees}

    return {
        "role": user.role,
        "cleaning": {
            "label": "Бонус за уборку: 500 ₽ / месяц",
            "year": year,
            "month": month,
            "status": "Условие выполнено" if status["eligible"] else ("Бонус не начислен" if status["missed"] else "Ожидается окончание месяца"),
            "required_count": status["required_count"],
            "completed_count": status["completed_count"],
            "missed": status["missed"],
        },
        "materialized_previous_month": {"created": created, "skipped": skipped},
        "items": [{
            "id": r.id,
            "employee_id": r.employee_id,
            "employee": names.get(r.employee_id),
            "amount": float(r.amount),
            "reason": r.reason,
            "source": r.source,
            "source_id": r.source_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in records],
    }
