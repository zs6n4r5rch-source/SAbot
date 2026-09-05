from pathlib import Path


def test_p0_shift_api_surface_and_server_wiring():
    root = Path(__file__).parents[1]
    routes = (root / "app" / "webapp" / "p0_routes.py").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/api/my-shift")' in routes
    assert '@app.get("/api/my-shift-close")' in routes
    assert '@app.post("/api/my-shift-close")' in routes
    assert "app.webapp.p0_routes" in main
    assert "await sync_shifts_data()" in routes
    assert "_submit_report" in routes


def test_p0_close_flow_keeps_langame_as_shift_source_of_truth():
    root = Path(__file__).parents[1]
    routes = (root / "app" / "webapp" / "p0_routes.py").read_text(encoding="utf-8")
    assert "shift.ended_at is None or shift.status != \"closed\"" in routes
    assert "Смена ещё открыта в LANGAME" in routes


def test_p0_models_are_exported_from_isolated_module():
    root = Path(__file__).parents[1]
    init = (root / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    salary = (root / "app" / "models" / "salary.py").read_text(encoding="utf-8")
    assert "_SALARY_EXPORTS" in init
    assert "def __getattr__(name):" in init
    assert "from app.models import salary" in init
    for name in ["ShiftCloseReport", "ShiftCloseStockItem", "SalaryPeriod", "SalaryViolation", "SalaryPayment", "NonMonetaryBonus"]:
        assert f"class {name}" in salary


def test_p0_financial_and_result_routes_are_registered_and_fresh():
    root = Path(__file__).parents[1]
    routes = (root / "app" / "webapp" / "p0_finance.py").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.post("/api/bonuses")' in routes
    assert '@app.get("/api/my-salary/current")' in routes
    assert '@app.get("/api/my-shift-result")' in routes
    assert "p0_finance" in main
    assert "calculate_period" in routes
    assert "SalaryAdjustment" in routes
    assert "SalaryViolation" in routes
    assert "shiftResult()" in routes
    assert "Посмотреть результат и зарплату" in routes
    assert "salary.total" in routes
    assert routes.count("await sync_shifts_data()") >= 3
    assert "math.isfinite(payload.amount)" in routes


def test_p0_manual_violation_is_linked_to_current_shift():
    root = Path(__file__).parents[1]
    penalties = (root / "app" / "bot" / "penalties.py").read_text(encoding="utf-8")
    assert "select(Shift).where(" in penalties
    assert "Shift.employee_id == employee_id" in penalties
    assert "Shift.ended_at.is_(None)" in penalties
    assert "shift_id=active_shift.id if active_shift else None" in penalties


def test_p0_salary_applies_violation_financial_impact():
    root = Path(__file__).parents[1]
    salary = (root / "app" / "bot" / "salary.py").read_text(encoding="utf-8")
    assert "fixed_penalties = sum" in salary
    assert "bonus_total = positive_bonuses + negative_adjustments - fixed_penalties" in salary
    assert "premium_reduction = any" in salary
    assert "positive_bonuses = Decimal(\"0\")" in salary
