from pathlib import Path


def test_active_mini_app_contains_management_sections():
    root = Path(__file__).parents[1]
    html = (root / "app" / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    for label in ["Главная", "Work Center", "Финансы", "Склад", "CRM", "Аналитика"]:
        assert label in html


def test_active_mini_app_uses_unified_api_routes():
    root = Path(__file__).parents[1]
    html = (root / "app" / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    for route in [
        "/api/app/overview",
        "/api/app/work-center",
        "/api/app/finance",
        "/api/app/warehouse",
        "/api/app/crm/groups",
        "/api/app/analytics",
    ]:
        assert route in html


def test_unified_server_exposes_active_mini_app_routes():
    root = Path(__file__).parents[1]
    text = (root / "app" / "webapp" / "unified_api.py").read_text(encoding="utf-8")
    for route in ["/overview", "/work-center", "/crm/groups", "/warehouse", "/finance", "/analytics"]:
        assert route in text


def test_unified_actions_are_mounted_and_guarded():
    root = Path(__file__).parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    actions = (root / "app" / "webapp" / "actions_api.py").read_text(encoding="utf-8")
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


def test_legacy_page_composer_is_non_mutating():
    root = Path(__file__).parents[1]
    source = (root / "app" / "webapp" / "page_composer.py").read_text(encoding="utf-8")
    assert "return html" in source
    assert "monkey-patching" in source
