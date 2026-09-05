from datetime import datetime, timezone
from decimal import Decimal
import math

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, SalaryAdjustment, SalaryPeriod, SalaryViolation, Shift, ShiftCloseReport, UserRole
from app.webapp.app import app, current_user, dec, iso


class BonusPayload(BaseModel):
    employee_id: int
    amount: float
    reason: str = Field(min_length=2, max_length=4000)


def _owner(user):
    if user.role != UserRole.OWNER.value:
        raise HTTPException(403, "OWNER access required")


def _admin(user):
    if user.role != UserRole.ADMIN.value or not user.employee_id:
        raise HTTPException(403, "ADMIN access required")


@app.post("/api/bonuses")
async def create_financial_bonus(request: Request, payload: BonusPayload):
    user, _ = await current_user(request)
    _owner(user)
    if not math.isfinite(payload.amount):
        raise HTTPException(400, "Сумма премии должна быть конечным числом")
    amount = Decimal(str(payload.amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(400, "Сумма премии должна быть больше нуля")
    from app.bot.salary import calculate_period, SHIFT_PAY, sync_shifts_data
    await sync_shifts_data()
    today = datetime.now(timezone.utc).date()
    date_from = today.replace(day=1)
    async with SessionLocal() as session:
        employee = await session.get(Employee, payload.employee_id)
        if employee is None or not employee.active:
            raise HTTPException(404, "Сотрудник не найден")
        period = await calculate_period(employee.id, date_from, today, SHIFT_PAY, session)
        if period.status in ("confirmed", "paid"):
            raise HTTPException(409, "Нельзя менять уже подтверждённую или выплаченную зарплату")
        adjustment = SalaryAdjustment(
            salary_period_id=period.id,
            amount=amount,
            reason=payload.reason.strip(),
            created_by=user.telegram_id,
        )
        session.add(adjustment)
        await session.flush()
        period = await calculate_period(employee.id, date_from, today, SHIFT_PAY, session)
        await session.commit()
        return {
            "ok": True,
            "adjustment_id": adjustment.id,
            "employee_id": employee.id,
            "period_id": period.id,
            "bonus": dec(period.bonus_amount),
            "total": dec(period.total_amount),
        }


@app.get("/api/my-salary/current")
async def my_salary_current(request: Request):
    user, _ = await current_user(request)
    _admin(user)
    from app.bot.salary import calculate_period, SHIFT_PAY, sync_shifts_data
    await sync_shifts_data()
    today = datetime.now(timezone.utc).date()
    async with SessionLocal() as session:
        period = await calculate_period(user.employee_id, today.replace(day=1), today, SHIFT_PAY, session)
        await session.commit()
        return {
            "period_id": period.id,
            "from": period.date_from.isoformat(),
            "to": period.date_to.isoformat(),
            "base": dec(period.base_amount),
            "bonus": dec(period.bonus_amount),
            "total": dec(period.total_amount),
            "status": period.status,
        }


@app.get("/api/my-shift-result")
async def my_shift_result(request: Request):
    user, _ = await current_user(request)
    _admin(user)
    from app.bot.salary import sync_shifts_data, calculate_period, SHIFT_PAY
    await sync_shifts_data()
    async with SessionLocal() as session:
        shift = (await session.execute(
            select(Shift).where(Shift.employee_id == user.employee_id)
            .order_by(Shift.started_at.desc()).limit(1)
        )).scalar_one_or_none()
        if shift is None:
            raise HTTPException(404, "Shift not found")
        report = await session.scalar(select(ShiftCloseReport).where(ShiftCloseReport.shift_id == shift.id))
        violations = (await session.execute(
            select(SalaryViolation).where(
                SalaryViolation.employee_id == user.employee_id,
                SalaryViolation.shift_id == shift.id,
            ).order_by(SalaryViolation.created_at.desc())
        )).scalars().all()
        today = datetime.now(timezone.utc).date()
        period = await calculate_period(user.employee_id, today.replace(day=1), today, SHIFT_PAY, session)
        adjustments = (await session.execute(
            select(SalaryAdjustment).where(SalaryAdjustment.salary_period_id == period.id)
        )).scalars().all()
        await session.commit()
        return {
            "shift": {
                "id": shift.id,
                "langame_shift_id": shift.langame_shift_id,
                "started_at": iso(shift.started_at),
                "ended_at": iso(shift.ended_at),
                "status": "open" if shift.ended_at is None else "closed",
            },
            "sales": {
                "cash": dec(shift.cash_sales),
                "card": dec(shift.card_sales),
                "mobile": dec(shift.mobile_sales),
                "refunds_cash": dec(shift.refunds_cash),
                "refunds_card": dec(shift.refunds_card),
                "collection": dec(shift.collection),
            },
            "close": {
                "status": report.status if report else None,
                "cash_expected": dec(report.cash_expected) if report else 0,
                "cash_actual": dec(report.cash_actual) if report else 0,
                "cash_difference": dec(report.cash_difference) if report else 0,
                "stock_discrepancies_count": report.stock_discrepancies_count if report else 0,
            },
            "bonuses": [
                {"amount": dec(a.amount), "reason": a.reason}
                for a in adjustments if Decimal(a.amount) > 0
            ],
            "violations": [
                {
                    "id": v.id,
                    "title": v.title,
                    "amount": dec(v.amount),
                    "premium_reduction_percent": dec(v.premium_reduction_percent),
                    "dismissal_required": v.dismissal_required,
                    "comment": v.comment,
                }
                for v in violations
            ],
            "salary": {
                "period_id": period.id,
                "base": dec(period.base_amount),
                "bonus": dec(period.bonus_amount),
                "total": dec(period.total_amount),
                "status": period.status,
            },
        }
