from app.models import (
    SalaryRule,
    SalaryPeriod,
    SalaryAdjustment,
    SalaryViolation,
    SalaryPayment,
    NonMonetaryBonus,
    ShiftCloseReport,
    ShiftCloseStockItem,
)


def test_salary_and_shift_close_models_are_exported():
    assert SalaryRule.__tablename__ == "salary_rules"
    assert SalaryPeriod.__tablename__ == "salary_periods"
    assert SalaryAdjustment.__tablename__ == "salary_adjustments"
    assert SalaryViolation.__tablename__ == "salary_violations"
    assert SalaryPayment.__tablename__ == "salary_payments"
    assert NonMonetaryBonus.__tablename__ == "non_monetary_bonuses"
    assert ShiftCloseReport.__tablename__ == "shift_close_reports"
    assert ShiftCloseStockItem.__tablename__ == "shift_close_stock_items"


def test_violation_contains_salary_and_hr_consequences():
    columns = SalaryViolation.__table__.columns
    assert {"amount", "premium_reduction_percent", "dismissal_required", "shift_id"}.issubset(columns.keys())


def test_shift_close_report_contains_cash_and_cleaning_state():
    columns = ShiftCloseReport.__table__.columns
    assert {"cash_expected", "cash_actual", "cash_difference", "submitted_at", "cleaning_confirmed_at"}.issubset(columns.keys())
