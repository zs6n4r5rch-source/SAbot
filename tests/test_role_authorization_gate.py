from pathlib import Path


def test_role_auth_assets_and_four_contours():
    auth = Path("app/webapp/static/auth-v2.js").read_text(encoding="utf-8")
    assert "Владелец" in auth
    assert "Администратор" in auth
    assert "SMM-специалист" in auth
    assert "Гость" in auth
    assert "/api/app/auth?role=" in auth
    assert "data-auth-role" in auth


def test_auth_api_enforces_staff_binding_and_guest_fallback():
    auth = Path("app/webapp/auth_api.py").read_text(encoding="utf-8")
    app = Path("app/webapp/app.py").read_text(encoding="utf-8")
    assert 'role == "guest"' in auth
    assert 'actual == UserRole.OWNER.value' in auth
    assert 'role not in ROLE_LABELS' in auth
    assert 'role="guest"' in app
    assert 'Every Telegram account can enter the public guest contour' in app


def test_mini_app_loads_auth_gate_before_design_layer():
    app = Path("app/webapp/app.py").read_text(encoding="utf-8")
    marker = '<script src="/static/auth-v2.js?v=1"></script>'
    assert marker in app
    assert app.index(marker) < app.index('design-v2.js?v=1')
