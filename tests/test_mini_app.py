from pathlib import Path


def test_mini_app_contains_all_owner_sections():
    root = Path(__file__).parents[1]
    html = (root / "app" / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    for label in ["Администраторы", "Клиенты", "Финансы", "Аналитика", "Бар и снеки", "Бонусы", "Штрафы", "Требует внимания", "Рассылки", "Настройки"]:
        assert label in html


def test_mini_app_has_server_api_sections():
    root = Path(__file__).parents[1]
    text = (root / "app" / "webapp" / "app.py").read_text(encoding="utf-8")
    for route in ["/api/admins", "/api/clients", "/api/inventory", "/api/finance", "/api/analytics", "/api/penalties", "/api/bonuses", "/api/shifts", "/api/attention", "/api/settings"]:
        assert f'@app.get("{route}")' in text


def test_feature_injections_do_not_add_nested_script_tags():
    root = Path(__file__).parents[1]
    admin = (root / "app" / "webapp" / "admin_shift_control.py").read_text(encoding="utf-8")
    summary = (root / "app" / "webapp" / "current_summary.py").read_text(encoding="utf-8")
    assert "JS = r'''<script>" not in admin
    assert "JS = r'''<script>" in summary
    assert "current_js = JS[len(\"<script>\"):-len(\"</script>\")]" in summary
