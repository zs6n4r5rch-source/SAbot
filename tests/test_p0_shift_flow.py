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
    assert "from app.models.salary import" in init
    for name in ["ShiftCloseReport", "ShiftCloseStockItem", "SalaryPeriod", "SalaryViolation", "SalaryPayment", "NonMonetaryBonus"]:
        assert f"class {name}" in salary
