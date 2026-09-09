from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_uses_single_mobile_navigation_surface():
    src = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    assert 'class="bottom"' in src
    assert 'data-more' in src
    assert 'Все разделы' in src
    assert 'data-page="overview"' in src
    assert 'data-page="work"' in src
    assert 'data-page="finance"' in src
    assert 'position:fixed;left:12px;right:12px;bottom:10px' in src


def test_domain_routes_have_dedicated_renderers():
    src = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    for name in ("overview", "work", "finance", "warehouse", "shifts", "previous", "closeReports", "penalties", "salary", "analytics", "crm", "crmSearch", "localLinks", "profiles", "admin", "settings", "campaigns", "guest"):
        assert "case'" + name + "':" in src


def test_mini_app_keeps_server_side_telegram_auth_for_every_read():
    src = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    assert "X-Telegram-Init-Data" in src
    assert "cache:'no-store'" in src
    assert "Telegram initData не получен" in src


def test_action_layer_matches_unified_navigation_and_custom_launcher():
    src = (ROOT / "app/webapp/static/actions-v2.js").read_text(encoding="utf-8")
    assert "document.querySelector('[data-page].active')" in src
    assert "sa:open-custom" in src
    assert "approve-writeoff" in src
    assert "confirm-salary" in src
    assert "pay-salary" in src
