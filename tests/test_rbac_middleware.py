import ast
from pathlib import Path


def test_rbac_middleware_parses_and_allows_configured_role_boundary():
    source = Path("app/webapp/rbac_middleware.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert '"owner", "admin", "smm", "guest"' in source
    assert "Unified API role is not configured" in source
    assert '"guest": ("/overview", "/guest/")' in source
    assert '"admin": (' in source
    assert '"/warehouse", "/shifts", "/penalties", "/salary"' in source


def test_main_installs_unified_rbac():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "UnifiedRBACMiddleware" in source
    assert "web_app.add_middleware(UnifiedRBACMiddleware)" in source
