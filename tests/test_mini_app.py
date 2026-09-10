from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "webapp" / "static"


def test_active_mini_app_contains_management_sections():
    guard = (STATIC / "app-guard.js").read_text(encoding="utf-8")
    for label in ["Главная", "Работа", "Финансы", "Склад", "CRM", "Аналитика"]:
        assert label in guard


def test_active_mini_app_uses_current_api_routes():
    guard = (STATIC / "app-guard.js").read_text(encoding="utf-8")
    for route in [
        "/api/app/live/overview",
        "/api/app/work-center",
        "/api/app/live/warehouse",
        "/api/app/crm/groups",
        "/api/app/live/analytics",
        "/api/app/shifts",
        "/api/app/shifts/previous",
        "/api/app/shifts/close-reports",
        "/api/app/penalties",
        "/api/app/settings",
        "/api/app/guest/me",
    ]:
        assert route in guard


def test_unified_server_exposes_active_mini_app_routes():
    text = (ROOT / "app" / "webapp" / "unified_api.py").read_text(encoding="utf-8")
    for route in ["/overview", "/work-center", "/crm/groups", "/warehouse", "/warehouse/arrivals", "/warehouse/sales", "/analytics", "/guest/me"]:
        assert route in text


def test_unified_actions_are_mounted_and_guarded():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    actions = (ROOT / "app" / "webapp" / "actions_api.py").read_text(encoding="utf-8")
    assert "actions_api_router" in main
    for route in [
        '/warehouse/writeoffs/{writeoff_id}/approve',
        '/warehouse/writeoffs/{writeoff_id}/reject',
        '/salary/{period_id}/confirm',
        '/salary/{period_id}/pay',
        '/settings',
    ]:
        assert route in actions
    assert "Permission.MANAGE_WAREHOUSE" in actions
    assert "Permission.MANAGE_FINANCE" in actions


def test_production_shell_injects_the_active_guard():
    source = (ROOT / "app" / "webapp" / "app.py").read_text(encoding="utf-8")
    assert "app-guard.js" in source
    assert "auth-v2.js" in source
    assert "design-v2.css" in source or "strike-design.css" in source


def test_legacy_page_composer_is_non_mutating():
    source = (ROOT / "app" / "webapp" / "page_composer.py").read_text(encoding="utf-8")
    assert "return html" in source
    assert "monkey-patching" in source
