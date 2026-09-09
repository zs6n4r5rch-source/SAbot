from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "webapp" / "static"


def _js_blocks(html: str):
    marker = "<script>"
    end = "</script>"
    out = []
    pos = 0
    while True:
        start = html.find(marker, pos)
        if start < 0:
            return out
        start += len(marker)
        finish = html.find(end, start)
        assert finish >= 0, "Unclosed inline script in Mini App HTML"
        out.append(html[start:finish])
        pos = finish + len(end)


def test_mini_app_boot_has_static_fallback_and_explicit_start_contract():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="app"' in html
    assert "Запуск приложения" in html
    assert "window.__SA_START_APP__" in html
    assert "sa:app-state" in html
    assert "state==='ready'" in html
    assert "state.role==='guest'?'guest':'overview'" in html


def test_mini_app_javascript_syntax():
    node = shutil.which("node")
    if node is None:
        return
    files = [STATIC / "auth-v2.js", STATIC / "design-v2.js"]
    for path in files:
        subprocess.run([node, "--check", str(path)], check=True, capture_output=True, text=True)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for block in _js_blocks(html):
        tmp = ROOT / ".mini_app_js_check.tmp.js"
        try:
            tmp.write_text(block, encoding="utf-8")
            subprocess.run([node, "--check", str(tmp)], check=True, capture_output=True, text=True)
        finally:
            tmp.unlink(missing_ok=True)


def test_auth_does_not_use_text_content_timeout_gate():
    auth = (STATIC / "auth-v2.js").read_text(encoding="utf-8")
    assert "textContent" not in auth
    assert "window.__SA_START_APP__" in auth


def test_design_has_no_global_mutation_observer():
    design = (STATIC / "design-v2.js").read_text(encoding="utf-8")
    assert "MutationObserver" not in design
    assert "sa:app-state" in design
