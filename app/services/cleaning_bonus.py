from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import BonusRecord, Employee, EmployeeClub, Shift, ShiftCloseReport

CLEANING_BONUS = Decimal("500.00")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    first = datetime.combine(date(year, month, 1), time.min, tzinfo=MOSCOW_TZ)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = datetime.combine(next_month, time.min, tzinfo=MOSCOW_TZ)
    return first, end


def is_night_shift(shift: Shift) -> bool:
    if not shift.started_at or not shift.ended_at or shift.ended_at <= shift.started_at:
        return False
    return shift.started_at.astimezone(MOSCOW_TZ).date() < shift.ended_at.astimezone(MOSCOW_TZ).date()


async def required_cleaning_shifts(session, year: int, month: int) -> list[Shift]:
    """Return the globally scheduled cleaning shifts falling in the calendar month.

    A cleaning is required after every second night shift in each club. The ordinal
    is calculated over the club's complete closed-shift history, so a month boundary
    does not reset the every-second-shift cadence.
    """
    start, end = month_bounds(year, month)
    result = await session.execute(
        select(Shift)
        .where(
            Shift.status == "closed",
            Shift.ended_at.is_not(None),
            Shift.ended_at >= start,
            Shift.ended_at < end,
        )
        .order_by(Shift.club_id.asc(), Shift.started_at.asc(), Shift.id.asc())
    )
    month_shifts = result.scalars().all()
    if not month_shifts:
        return []

    clubs = sorted({s.club_id for s in month_shifts})
    required: list[Shift] = []
    for club_id in clubs:
        history_result = await session.execute(
            select(Shift)
            .where(
                Shift.club_id == club_id,
                Shift.status == "closed",
                Shift.ended_at.is_not(None),
                Shift.started_at.is_not(None),
            )
            .order_by(Shift.started_at.asc(), Shift.id.asc())
        )
        ordinal = 0
        for shift in history_result.scalars().all():
            if not is_night_shift(shift):
                continue
            ordinal += 1
            if ordinal % 2 == 0 and start <= shift.ended_at.astimezone(MOSCOW_TZ) < end:
                required.append(shift)
    return sorted(required, key=lambda s: (s.ended_at or s.started_at, s.id))


async def cleaning_bonus_status(session, year: int, month: int) -> dict:
    """Calculate monthly team eligibility without creating ledger records."""
    required = await required_cleaning_shifts(session, year, month)
    missed: list[dict] = []
    for shift in required:
        report = await session.scalar(
            select(ShiftCloseReport).where(ShiftCloseReport.shift_id == shift.id)
        )
        if report is None or report.cleaning_confirmed_at is None:
            missed.append({
                "shift_id": shift.id,
                "langame_shift_id": shift.langame_shift_id,
                "club_id": shift.club_id,
                "ended_at": shift.ended_at.isoformat() if shift.ended_at else None,
            })

    return {
        "year": year,
        "month": month,
        "amount": CLEANING_BONUS,
        "required_count": len(required),
        "completed_count": len(required) - len(missed),
        "missed": missed,
        "eligible": bool(required) and not missed,
    }


async def materialize_monthly_cleaning_bonus(session, year: int, month: int) -> tuple[int, int, dict]:
    """Create one 500 ₽ record per active admin when the whole club/team qualifies.

    The ledger key is calendar-month based, making repeated scheduler/manual runs
    idempotent. The function intentionally does not award anything when no required
    cleaning exists yet.
    """
    status = await cleaning_bonus_status(session, year, month)
    if not status["eligible"]:
        return 0, 0, status

    employees = (await session.execute(
        select(Employee).join(EmployeeClub, EmployeeClub.employee_id == Employee.id)
        .where(Employee.active.is_(True))
        .distinct()
        .order_by(Employee.id.asc())
    )).scalars().all()

    created = skipped = 0
    source = "cleaning_monthly"
    for employee in employees:
        source_id = f"{year:04d}-{month:02d}:{employee.id}"
        exists = await session.scalar(
            select(BonusRecord.id).where(
                BonusRecord.source == source,
                BonusRecord.source_id == source_id,
            )
        )
        if exists is not None:
            skipped += 1
            continue
        session.add(BonusRecord(
            employee_id=employee.id,
            amount=CLEANING_BONUS,
            reason="Бонус за уборку: 500 ₽ / месяц",
            source=source,
            source_id=source_id,
        ))
        created += 1
    return created, skipped, status
