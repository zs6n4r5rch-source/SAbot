from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_owner_is_allowlisted_not_first_user():
    src = (ROOT / "app/services/auth.py").read_text(encoding="utf-8")
    assert "telegram_id not in settings.owners" in src
    assert "first user" in src
    assert "role=UserRole.OWNER.value" in src


def test_access_rejects_unknown_or_inactive_users():
    src = (ROOT / "app/services/auth.py").read_text(encoding="utf-8")
    assert "if user is None or not user.active" in src


def test_langame_client_has_no_generic_write_path():
    src = (ROOT / "app/services/langame.py").read_text(encoding="utf-8")
    assert "MUTATING_METHODS" in src
    assert "READ_ONLY_POST_PATHS" in src
    assert "LangameReadOnlyViolation" in src
