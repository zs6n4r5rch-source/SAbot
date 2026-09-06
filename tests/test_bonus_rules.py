from pathlib import Path
ROOT = Path(__file__).parents[1]

def test_bonus_rules_and_review_bonus_are_present():
    salary = (ROOT / "app" / "bot" / "salary.py").read_text()
    models = (ROOT / "app" / "models" / "salary.py").read_text()
    migration = (ROOT / "alembic" / "versions" / "0015_bonuses_and_cleaning.py").read_text()
    assert 'IDEAL_CLOSE_MONTHLY_BONUS = Decimal("250.00")' in salary
    assert 'CASH_DISCIPLINE_MONTHLY_BONUS = Decimal("250.00")' in salary
    assert 'BAR_THRESHOLD = Decimal("30000.00")' in salary
    assert 'BAR_BASE_RATE = Decimal("0.05")' in salary
    assert 'BAR_EXCESS_RATE = Decimal("0.05")' in salary
    assert 'BAR_TOP_RATE = Decimal("0.05")' in salary
    assert 'class NonMonetaryBonus(Base):' in models
    assert 'non_monetary_bonuses' in migration
    assert 'Бонус за отзыв гостя' in salary

def test_cleaning_is_every_second_night_shift_and_has_performer():
    closing = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    models = (ROOT / "app" / "models" / "salary.py").read_text()
    assert 'return position % 2 == 0' in closing
    assert 'waiting_cleaning_performer' in closing
    assert 'cleaning_performed_by' in closing
    assert 'cleaning_performed_by: Mapped[str | None]' in models
