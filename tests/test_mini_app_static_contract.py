from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "webapp" / "static"


def test_mini_app_boot_has_static_fallback_and_explicit_start_contract():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    guard = (STATIC / "app-guard.js").read_text(encoding="utf-8")
    role_ui = (STATIC / "role-ui-v2.js").read_text(encoding="utf-8")
    assert 'id="app"' in html
    assert "Запуск приложения" in html
    assert "window.__SA_START_APP__" in html
    assert "window.__SA_QA_CAN__" in guard
    assert "sa:app-state" in role_ui
    assert "signal('loading')" in role_ui
    assert "signal('ready')" in role_ui
    assert "state==='ready'" in role_ui


def test_mini_app_javascript_syntax():
    node = shutil.which("node")
    if node is None:
        return
    files = [
        STATIC / "app-guard.js",
        STATIC / "auth-v2.js",
        STATIC / "design-v2.js",
        STATIC / "role-ui-v2.js",
        STATIC / "actions-v2.js",
    ]
    for path in files:
        subprocess.run([node, "--check", str(path)], check=True, capture_output=True, text=True)


def test_auth_uses_explicit_app_bootstrap_contract():
    auth = (STATIC / "auth-v2.js").read_text(encoding="utf-8")
    assert "window.__SA_START_APP__" in auth
    assert "startApplication" in auth
    assert "setTimeout(function(){var app=document.getElementById('app')" not in auth


def test_design_has_no_global_mutation_observer_and_smm_surface_is_explicit():
    design = (STATIC / "design-v2.js").read_text(encoding="utf-8")
    role_ui = (STATIC / "role-ui-v2.js").read_text(encoding="utf-8")
    assert "MutationObserver" not in design
    assert "role-ui-v2.js" in design
    assert "sa:app-state" in role_ui
