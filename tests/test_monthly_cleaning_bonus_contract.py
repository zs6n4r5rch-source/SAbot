from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cleaning_bonus_service_is_monthly_and_idempotent():
    source = (ROOT / "app" / "services" / "cleaning_bonus.py").read_text()
    assert 'CLEANING_BONUS = Decimal("500.00")' in source
    assert 'source = "cleaning_monthly"' in source
    assert 'source_id = f"{year:04d}-{month:02d}:{employee.id}"' in source
    assert 'if not status["eligible"]:' in source
    assert 'report.cleaning_confirmed_at is None' in source


def test_shift_close_uses_every_second_night_shift_and_never_awards_per_confirmation():
    closing = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    assert 'return position % 2 == 0' in closing
    assert 'report.cleaning_bonus_amount = Decimal("0.00")' in closing
    assert 'За подтверждённую уборку начисляется бонус' not in closing


def test_bonus_api_is_owner_or_own_admin_only():
    api = (ROOT / "app" / "webapp" / "bonuses_api.py").read_text()
    assert 'UserRole.OWNER.value, UserRole.ADMIN.value' in api
    assert 'BonusRecord.employee_id == user.employee_id' in api
    assert 'materialize_monthly_cleaning_bonus' in api


def test_bonus_ui_is_available_to_owner_and_admin_without_salary():
    ui = (ROOT / "app" / "webapp" / "static" / "app-ux-v12.js").read_text()
    assert "['owner','admin']" in ui
    assert "Бонус за уборку: 500 ₽ / месяц" in ui
    assert "Бонусы" in ui
    assert "salary" not in ui.lower()
