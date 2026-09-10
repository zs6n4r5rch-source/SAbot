from pathlib import Path


def test_guest_role_is_limited_to_guest_contour():
    source = Path("app/webapp/rbac_middleware.py").read_text(encoding="utf-8")
    assert '"guest": ("/guest/",)' in source
    assert 'ROLE_PATHS[role]' in source
    assert 'Раздел недоступен для этой роли' in source


def test_guest_profile_exposes_only_verified_identity_and_consent():
    source = Path("app/webapp/unified_api.py").read_text(encoding="utf-8")
    assert '@router.get("/guest/me")' in source
    assert 'need(user, Permission.OWN_PROFILE)' in source
    assert 'GuestTelegram.telegram_user_id == user.telegram_id' in source
    assert '"balance": None' in source
    assert '"bonuses": None' in source
    assert '"marketing_consent": tg.marketing_consent' in source
    assert '"guest": {' in source


def test_guest_contour_does_not_grant_finance_or_warehouse_sections():
    source = Path("app/webapp/rbac_middleware.py").read_text(encoding="utf-8")
    guest_line = next(line for line in source.splitlines() if '"guest":' in line)
    assert "/finance" not in guest_line
    assert "/warehouse" not in guest_line
    assert "/analytics" not in guest_line
