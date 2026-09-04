from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func

from app.models import Employee, TelegramUser, UserRole
from app.models.smm import SMMAccess, SMMTask, SMMTaskRate

SMM_ROLE = "smm"
DEFAULT_ANALYTICS = {"social", "guests", "marketing", "advertising"}


def has_analytics(access: SMMAccess | None, area: str) -> bool:
    if not access or not access.active:
        return False
    allowed = {x.strip() for x in (access.analytics_access or "").split(",") if x.strip()}
    return area in allowed


async def get_smm_access(session, telegram_id: int):
    return (await session.execute(
        select(SMMAccess).where(SMMAccess.telegram_user_id == telegram_id, SMMAccess.active.is_(True))
    )).scalar_one_or_none()


async def assign_smm(session, telegram_id: int, employee_id: int | None = None, analytics=None):
    user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        raise ValueError("Telegram-пользователь не найден")
    access = (await session.execute(select(SMMAccess).where(SMMAccess.telegram_user_id == telegram_id))).scalar_one_or_none()
    if not access:
        access = SMMAccess(telegram_user_id=telegram_id)
        session.add(access)
    access.employee_id = employee_id or user.employee_id
    access.analytics_access = ",".join(sorted(analytics or DEFAULT_ANALYTICS))
    access.active = True
    return access


async def submit_task(session, employee_id: int, task_type: str, title: str, quantity: Decimal, proof: str | None = None, comment: str | None = None):
    rate = (await session.execute(select(SMMTaskRate).where(SMMTaskRate.task_type == task_type, SMMTaskRate.active.is_(True)))).scalar_one_or_none()
    if not rate:
        raise ValueError("Для этого типа работы не задан тариф")
    task = SMMTask(employee_id=employee_id, task_type=task_type, title=title, quantity=quantity, unit=rate.unit, unit_rate=rate.rate, proof=proof, comment=comment)
    session.add(task)
    await session.flush()
    return task


async def smm_payroll(session, employee_id: int, days: int = 30):
    start = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
    rows = (await session.execute(select(SMMTask).where(SMMTask.employee_id == employee_id, SMMTask.status == "approved", SMMTask.submitted_at >= start))).scalars().all()
    amount = sum((Decimal(r.quantity or 0) * Decimal(r.unit_rate or 0) for r in rows), Decimal("0"))
    return {"tasks": len(rows), "amount": amount, "items": rows}
