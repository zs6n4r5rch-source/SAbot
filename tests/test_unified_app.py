import ast
from pathlib import Path


def test_unified_api_parses():
    ast.parse(Path("app/webapp/unified_api.py").read_text(encoding="utf-8"))


def test_main_parses():
    ast.parse(Path("app/main.py").read_text(encoding="utf-8"))


def test_unified_shell_exists():
    html = Path("app/webapp/static/index_v2.html").read_text(encoding="utf-8")
    for marker in ["api('overview')", "api('work-center')", "api('crm/groups')", "api('finance", "api('warehouse')"]:
        assert marker in html
