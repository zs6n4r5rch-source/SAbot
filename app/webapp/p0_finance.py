from datetime import datetime, timezone
from decimal import Decimal
import math

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
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


def _period_for_date(value):
    return value.replace(day=1), (value.replace(day=1).replace(day=28) + __import__('datetime').timedelta(days=4)).replace(day=1) - __import__('datetime').timedelta(days=1)


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
        shift_date = (shift.started_at.astimezone(timezone.utc).date() if shift.started_at.tzinfo else shift.started_at.date())
        date_from, date_to = _period_for_date(shift_date)
        period = await calculate_period(user.employee_id, date_from, date_to, SHIFT_PAY, session)
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


@app.middleware("http")
async def p0_shift_result_ux(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/" or response.status_code != 200:
        return response
    body = getattr(response, "body", None)
    if body is None:
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        body = b"".join(chunks)
    html = body.decode("utf-8")
    marker = "Смена зафиксирована. Зарплата пересчитывается по закрытым сменам и начислениям."
    html = html.replace(
        marker,
        marker + '<br><br><button class="secondary" onclick="shiftResult()">Посмотреть результат и зарплату</button>',
        1,
    )
    fn = r'''
async function shiftResult(){
  clear();setBottom(false);back();
  try{
    const d=await api('/api/my-shift-result');
    const bonuses=(d.bonuses||[]).map(x=>row('Премия',money(x.amount),x.reason||'')).join('')||'<div class="empty">Нет зафиксированных премий.</div>';
    const violations=(d.violations||[]).map(x=>row('Нарушение',money(x.amount),`${x.title}${x.dismissal_required?' · требуется решение':''}`)).join('')||'<div class="empty">Нарушений по смене нет.</div>';
    root.innerHTML=`<section class="hero"><div class="eyebrow">Результат смены</div><div class="hero-title">Смена #${d.shift.langame_shift_id}</div><div class="hero-sub">Итог работы, закрытия и начислений.</div></section>${card('Продажи',`${row('Наличные',money(d.sales.cash))}${row('Карта',money(d.sales.card))}${row('Мобильные',money(d.sales.mobile))}${row('Возвраты наличными',money(d.sales.refunds_cash))}${row('Возвраты картой',money(d.sales.refunds_card))}${row('Инкассация',money(d.sales.collection))}`)}${card('Закрытие',`${row('Кассовая разница',money(d.close.cash_difference))}${row('Расхождения товаров',d.close.stock_discrepancies_count||0)}${row('Статус',d.close.status||'—')}`)}${card('Премии',bonuses)}${card('Нарушения',violations)}${card('Зарплата',`${row('База',money(d.salary.base))}${row('Премии / корректировки',money(d.salary.bonus))}<div class="section-title"><h2>Итого</h2><span>${d.salary.status}</span></div><div class="hero-title">${money(d.salary.total)}</div>`)}`;
  }catch(e){fail(e)}
}
'''
    html = html.replace("\nfunction goNav(which)", "\n" + fn + "\nfunction goNav(which)", 1)
    return HTMLResponse(html, status_code=response.status_code, headers={k:v for k,v in response.headers.items() if k.lower() != "content-length"})
