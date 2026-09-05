from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_owner_models_are_exported_for_web_and_daily_report_flows():
    src = (ROOT / "app/models/__init__.py").read_text(encoding="utf-8")
    assert "from app.models.owner import Guest, GuestTelegram, OwnerDailyReportDelivery, OwnerReportSettings" in src
    assert '"OwnerReportSettings"' in src
    assert '"OwnerDailyReportDelivery"' in src


def test_owner_attention_is_detailed_and_actionable():
    src = (ROOT / "app/webapp/owner_routes.py").read_text(encoding="utf-8")
    assert '@app.get("/api/owner/attention")' in src
    assert "critical_stock" in src
    assert "cash_issue" in src
    assert "dismissal_required" in src
    assert "Открыть остатки" in src
    assert "Открыть контроль смен" in src
    assert "Открыть нарушения" in src


def test_owner_report_settings_can_be_saved_and_validated():
    src = (ROOT / "app/webapp/owner_routes.py").read_text(encoding="utf-8")
    assert '@app.put("/api/owner/report-settings")' in src
    assert "ZoneInfo(payload.timezone)" in src
    assert "cfg.report_timezone = payload.timezone" in src
    assert "cfg.send_excel = payload.send_excel" in src


def test_owner_module_is_registered_after_ia_module():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "import app.webapp.p1_routes" in src
    assert "import app.webapp.owner_routes" in src
    assert src.index("import app.webapp.p1_routes") < src.index("import app.webapp.owner_routes")
