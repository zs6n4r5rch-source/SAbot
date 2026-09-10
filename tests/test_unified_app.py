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
    assert "/api/app/finance" in html
    assert "/api/app/warehouse" in html


def test_live_refresh_layer_is_present():
    source = (ROOT / "app/webapp/static/app-ux-v10.js").read_text(encoding="utf-8")
    assert "/api/app/warehouse" in source
    assert "/api/app/overview" in source
    assert "/api/app/finance" in source
    assert "setInterval(fn,20000)" in source
