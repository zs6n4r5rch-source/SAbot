from pathlib import Path


def test_shift_result_uses_shift_month_for_salary_period():
    root = Path(__file__).parents[1]
    source = (root / "app" / "webapp" / "p0_finance.py").read_text(encoding="utf-8")
    assert "shift_date =" in source
    assert "date_from, date_to = _period_for_date(shift_date)" in source
    assert "today.replace(day=1), today" not in source[source.index('@app.get("/api/my-shift-result")'):]


def test_shift_result_exposes_only_shift_linked_violations():
    root = Path(__file__).parents[1]
    source = (root / "app" / "webapp" / "p0_finance.py").read_text(encoding="utf-8")
    result_block = source[source.index('@app.get("/api/my-shift-result")'):source.index('@app.middleware("http")')]
    assert "SalaryViolation.shift_id == shift.id" in result_block


def test_langame_sync_remains_source_of_truth_for_duplicate_shift_prevention():
    root = Path(__file__).parents[1]
    source = (root / "app" / "bot" / "salary.py").read_text(encoding="utf-8")
    assert "Shift.langame_shift_id == int(sid)" in source
    assert "if shift is None:" in source
    assert "shift.status = \"closed\" if ended else \"open\"" in source
