from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cleaning_bonus_is_monthly_not_per_shift():
    salary = (ROOT / "app" / "bot" / "salary.py").read_text()
    closing = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    assert 'CLEANING_MONTHLY_BONUS = Decimal("500.00")' in salary
    assert "monthly_cleaning_bonus(employee_id, date_from, date_to, session)" in salary
    assert "report.cleaning_bonus_amount = Decimal(\"0.00\")" in closing
    assert "cleaning_bonus_amount), 0" not in salary


def test_cleaning_bonus_requires_completed_calendar_month_and_all_night_shifts():
    salary = (ROOT / "app" / "bot" / "salary.py").read_text()
    assert "if not _is_full_calendar_month(date_from, date_to):" in salary
    assert "if date_to >= today_moscow:" in salary
    assert "if not night_shifts:" in salary
    assert "scheduled_ids" in salary
    assert "cleaning_performed_by" in salary


def test_shift_close_message_does_not_promise_500_per_shift():
    closing = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    assert "будет начислен единоразовый бонус" in closing
    assert "За подтверждённую уборку начисляется бонус" not in closing
