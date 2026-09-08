import ast
from pathlib import Path


def test_rbac_middleware_parses_and_has_guest_deny_policy():
    source = Path("app/webapp/rbac_middleware.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "Unified management API is restricted to OWNER/ADMIN" in source
    assert '"owner", "admin"' in source


def test_main_installs_unified_rbac():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "UnifiedRBACMiddleware" in source
    assert "web_app.add_middleware(UnifiedRBACMiddleware)" in source
