from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_owner_provisioning_uses_configured_staff_roster_not_first_user():
    staff_src = (ROOT / "app/services/staff_access.py").read_text(encoding="utf-8")
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    start_src = (ROOT / "app/bot/start.py").read_text(encoding="utf-8")

    assert "REAL_STAFF" in staff_src
    assert "UserRole.OWNER.value" in staff_src
    assert "ensure_real_staff_profiles" in main_src
    assert "process_staff_start" in start_src


def test_legacy_bootstrap_owner_helper_is_removed():
    matches = list((ROOT / "app").rglob("*.py"))
    assert all("ensure_bootstrap_owner" not in path.read_text(encoding="utf-8") for path in matches)


def test_access_rejects_unknown_or_inactive_users():
    src = (ROOT / "app/services/auth.py").read_text(encoding="utf-8")
    assert "if user is None or not user.active" in src


def test_langame_client_has_no_generic_write_path():
    src = (ROOT / "app/services/langame.py").read_text(encoding="utf-8")
    assert "MUTATING_METHODS" in src
    assert "READ_ONLY_POST_PATHS" in src
    assert "LangameReadOnlyViolation" in src
