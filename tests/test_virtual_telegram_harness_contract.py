from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_virtual_telegram_harness_covers_real_security_layers():
    path = ROOT / "tests" / "virtual_telegram" / "test_rbac_e2e.py"
    text = path.read_text(encoding="utf-8")
    assert "validate_init_data" not in text
    assert "X-Telegram-Init-Data" in text
    assert "test_tampered_init_data_is_rejected" in text
    assert "test_admin_never_sees_salary_even_with_shift_permission" in text
    assert "test_owner_preview_is_authorized_but_does_not_change_actual_identity" in text


def test_frontend_admin_policy_hides_owner_only_sections():
    text = (ROOT / "app" / "webapp" / "static" / "admin-policy.js").read_text(encoding="utf-8")
    for section in ("salary", "penalties", "admin", "profiles", "settings"):
        assert f'data-page=\\"{section}\\"' in text
        assert f'data-drawer-page=\\"{section}\\"' in text


def test_frontend_admin_policy_matches_server_owner_only_boundaries():
    rbac = (ROOT / "app" / "webapp" / "rbac_middleware.py").read_text(encoding="utf-8")
    policy = (ROOT / "app" / "webapp" / "static" / "admin-policy.js").read_text(encoding="utf-8")
    assert 'path=="/api/app/salary" and role!="owner"' in rbac
    assert 'path=="/api/app/penalties" and role!="owner"' in rbac
    for section in ("salary", "penalties"):
        assert f'data-page=\\"{section}\\"' in policy
        assert f'data-drawer-page=\\"{section}\\"' in policy
