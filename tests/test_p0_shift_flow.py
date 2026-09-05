from pathlib import Path


def test_p0_shift_api_surface_and_main_wiring():
    root = Path(__file__).parents[1]
    routes = (root / "app" / "webapp" / "p0_routes.py").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    for route in ["/api/my-shift", "/api/my-shift-close"]:
        assert f'@app.get("{route}")' in routes
    assert '@app.post("/api/my-shift-close")' in routes
    assert "app.webapp.p0_routes" in main
    assert "await sync_shifts_data()" in routes
    assert "_submit_report" in routes


def test_p0_close_flow_does_not_create_or_modify_langame_shift():
    root = Path(__file__).parents[1]
    routes = (root / "app" / "webapp" / "p0_routes.py").read_text(encoding="utf-8")
    assert "langame_shift_id" in routes
    assert "shift.ended_at is None or shift.status != \"closed\"" in routes
    assert "Смена ещё открыта в LANGAME" in routes


def test_inventory_model_keeps_zero_quantity_and_five_minimum_stock():
    root = Path(__file__).parents[1]
    text = (root / "app" / "models" / "base.py").read_text(encoding="utf-8")
    assert 'quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0' in text
    assert 'min_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=5, server_default="5")' in text
