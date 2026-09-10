import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_unified_api_parses():
    ast.parse((ROOT / "app/webapp/unified_api.py").read_text(encoding="utf-8"))


def test_main_parses():
    ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))


def test_production_shell_is_the_tested_shell():
    html = (ROOT / "app/webapp/static/index.html").read_text(encoding="utf-8")
    assert 'id="app"' in html
    assert 'id="drawer"' in html
    assert "app-guard.js" in html
    assert "auth-v2.js" in html


def test_live_dashboard_contract_is_present():
    src = (ROOT / "app/webapp/static/app-guard.js").read_text(encoding="utf-8")
    assert "/api/app/live/overview" in src
    assert "/api/app/live/warehouse" in src
    assert "/api/app/live/analytics" in src
    assert "params.period='month'" in src
    assert "setInterval(function(){if(document.visibilityState==='visible')load(false,true)},20000)" in src
