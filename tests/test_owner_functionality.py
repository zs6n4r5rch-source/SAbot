from importlib import import_module
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_owner_models_are_exported_for_web_daily_report_and_mailings():
    src = (ROOT / "app/models/__init__.py").read_text(encoding="utf-8")
    assert "from app.models.owner import (" in src
    assert '"GuestGroup"' in src
    assert '"MarketingCampaign"' in src
    assert '"MarketingRecipient"' in src
    assert '"OwnerReportSettings"' in src
    assert '"OwnerDailyReportDelivery"' in src


def test_owner_runtime_modules_import_without_model_registration_errors(monkeypatch):
    # The import test must not require a production database driver. Patch the
    # engine factory before importing the modules that create the DB session.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("LANGAME_API_KEY", "ci-test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ci-test-token")

    import sqlalchemy.ext.asyncio
    monkeypatch.setattr(
        sqlalchemy.ext.asyncio,
        "create_async_engine",
        lambda *args, **kwargs: object(),
    )
    import_module("app.webapp.owner_routes")
    import_module("app.bot.mailing")


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


def test_owner_mailing_router_is_registered():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "from app.bot.mailing import router as mailing_router" in src
    assert "dp.include_router(mailing_router)" in src


def test_owner_module_is_registered_after_ia_module():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "import app.webapp.p1_routes" in src
    assert "import app.webapp.owner_routes" in src
    assert src.index("import app.webapp.p1_routes") < src.index("import app.webapp.owner_routes")


def test_mini_app_menu_has_no_known_dead_or_placeholder_transitions():
    src = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    p0 = (ROOT / "app/webapp/p0_routes.py").read_text(encoding="utf-8")
    p1 = (ROOT / "app/webapp/p1_routes.py").read_text(encoding="utf-8")

    # The legacy close-shift action is rewritten by p0_routes middleware.
    assert "function closeShift()" in p0
    assert "Закрытие смены выполняется через рабочий экран бота." in src

    # Every named function used by the role-based menu must exist in the SPA.
    required = {
        "admins", "clients", "finance", "analytics", "inventory", "penalties",
        "bonuses", "attention", "mailings", "settings", "shifts", "salary",
    }
    declared = set(re.findall(r"(?:async )?function ([a-zA-Z_$][\w$]*)\s*\(", src))
    missing = sorted(required - declared)
    assert not missing, f"Menu points to undefined functions: {missing}"

    # IA rename is applied at runtime, so both the replacement and the old
    # label must be represented intentionally in the middleware.
    assert 'html.replace("Штрафы · 30 дней", "Нарушения · 30 дней")' in p1
    assert 'html.replace("\'Штрафы\'", "\'Нарушения\'")' in p1


def test_owner_ia_exposes_action_center_and_settings():
    src = (ROOT / "app/webapp/owner_routes.py").read_text(encoding="utf-8")
    assert "window.attention=async function()" in src
    assert "window.settings=async function()" in src
    assert "/api/owner/attention" in src
    assert "/api/owner/report-settings" in src
