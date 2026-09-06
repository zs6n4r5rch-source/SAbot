from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models import BonusRecord, SalaryAdjustment, SalaryPeriod


async def sync_salary_adjustments_to_bonus_records(session, period: SalaryPeriod) -> tuple[int, int]:
    """Materialize positive salary adjustments as idempotent monetary bonus records.

    Returns (created, skipped). The salary adjustment remains the source of truth;
    BonusRecord is an auditable ledger projection keyed by period + adjustment id.
    """
    if period.status not in {"confirmed", "paid"}:
        return 0, 0

    result = await session.execute(
        select(SalaryAdjustment).where(
            SalaryAdjustment.salary_period_id == period.id,
            SalaryAdjustment.amount > 0,
        ).order_by(SalaryAdjustment.id.asc())
    )
    adjustments = result.scalars().all()
    created = skipped = 0
    for adjustment in adjustments:
        source = "salary_adjustment"
        source_id = f"{period.id}:{adjustment.id}"
        existing = await session.execute(
            select(BonusRecord.id).where(
                BonusRecord.source == source,
                BonusRecord.source_id == source_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue
        session.add(BonusRecord(
            employee_id=period.employee_id,
            amount=Decimal(adjustment.amount),
            reason=adjustment.reason,
            source=source,
            source_id=source_id,
            created_at=adjustment.created_at,
        ))
        await session.flush()
        created += 1
    return created, skipped
