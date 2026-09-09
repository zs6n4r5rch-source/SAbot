from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mini_app_has_static_fallback_and_deterministic_start_contract():
    src = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    assert "boot-fallback" in src
    assert "window.__SA_START_APP__" in src
    assert "X-Telegram-Init-Data" in src
    assert "cache:'no-store'" in src
    assert "sa:app-state" in src
    assert "state==='ready'" in src


def test_auth_gate_does_not_disappear_before_application_start():
    src = (ROOT / "app/webapp/static/auth-v2.js").read_text(encoding="utf-8")
    assert "await startApplication(d);" in src
    assert "document.body.classList.remove('sa-auth-open')" in src
    assert "Основное приложение не инициализировано" in src
    assert "Telegram WebApp не готов" in src


def test_root_shell_disables_http_caching_and_uses_revisioned_assets():
    src = (ROOT / "app/webapp/app.py").read_text(encoding="utf-8")
    assert 'Cache-Control"].*no-store' in src or 'Cache-Control"] = "no-store' in src
    assert "auth-v2.js?v=11" in src
    assert "design-v2.css?v=11" in src
    assert "telegram-web-app.js" in src


def test_actions_always_send_telegram_init_data_and_no_store():
    src = (ROOT / "app/webapp/static/actions-v2.js").read_text(encoding="utf-8")
    assert "X-Telegram-Init-Data" in src
    assert "cache:'no-store'" in src
    assert "data-sa-action" in src
    assert "data-sa-save" in src
