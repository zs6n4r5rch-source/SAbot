import ast
from pathlib import Path


def test_rbac_middleware_parses_and_defines_all_role_boundaries():
    source = Path("app/webapp/rbac_middleware.py").read_text(encoding="utf-8")
    ast.parse(source)
    for role in ("owner", "admin", "smm", "guest"):
        assert f'"{role}"' in source
    assert "Unified API role is not configured" in source
    assert "Salary access is restricted to owner" in source
    assert "Admin is operational only" in source


def test_main_installs_unified_rbac():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "UnifiedRBACMiddleware" in source
    assert "web_app.add_middleware(UnifiedRBACMiddleware)" in source
