from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import BonusRecord, SalaryAdjustment, SalaryPeriod
from app.services.bonus_records import sync_salary_adjustments_to_bonus_records


@pytest.mark.asyncio
async def test_sync_salary_adjustments_is_idempotent(db_session):
    period = SalaryPeriod(
        employee_id=1,
        date_from=datetime(2026, 8, 1, tzinfo=timezone.utc).date(),
        date_to=datetime(2026, 8, 31, tzinfo=timezone.utc).date(),
        status="confirmed",
    )
    db_session.add(period)
    await db_session.flush()
    adjustment = SalaryAdjustment(
        salary_period_id=period.id,
        amount=Decimal("750.00"),
        reason="Тестовая премия",
        created_by=1,
    )
    db_session.add(adjustment)
    await db_session.flush()

    created, skipped = await sync_salary_adjustments_to_bonus_records(db_session, period)
    assert (created, skipped) == (1, 0)
    await db_session.commit()

    created, skipped = await sync_salary_adjustments_to_bonus_records(db_session, period)
    assert (created, skipped) == (0, 1)

    record = await db_session.get(BonusRecord, 1)
    assert record is not None
    assert record.amount == Decimal("750.00")
    assert record.source == "salary_adjustment"
    assert record.source_id == str(adjustment.id)
