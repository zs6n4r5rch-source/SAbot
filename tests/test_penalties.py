from decimal import Decimal
from pathlib import Path


def test_penalty_catalog_contains_all_policy_codes():
    text = Path("app/bot/penalties.py").read_text()
    for code in [
        "smoking", "dirty_area", "guest_drinks", "uniform", "entrance_trash", "late_request",
        "off_schedule_open", "cash_discipline", "strangers", "commercial_break", "secret_shopper",
        "receipt_money", "discount_abuse", "insult_sa", "greeting", "collection_guest_number",
        "telegram_report", "empty_fridge", "overflowing_bins", "sleeping_guest", "game_update",
        "device_issue", "alcohol", "guest_table_trash", "pc_restore", "work_phone", "late_1h",
        "sleeping_admin", "no_show",
    ]:
        assert f'("{code}"' in text


def test_premium_reduction_rules_are_not_fixed_money_penalties():
    text = Path("app/bot/penalties.py").read_text()
    assert '"receipt_money", "🧾 Деньги не внесены при выданном чеке", Decimal("0"), False, True' in text
    assert '"discount_abuse", "🏷 Присвоение/злоупотребление через скидки, неверную цену и т.п.", Decimal("0"), False, True' in text


def test_fixed_shift_pay_remains_2000():
    text = Path("app/bot/salary.py").read_text()
    assert 'SHIFT_PAY = Decimal("2000.00")' in text


def test_automatic_late_report_penalty_is_deduplicated():
    text = Path("app/bot/penalties.py").read_text()
    assert 'source_key = f"auto:telegram_report:{report.shift_id}"' in text
    assert 'SalaryViolation.source_key == source_key' in text


def test_insult_sa_policy_is_500_first_and_dismissal_on_repeat():
    text = Path("app/bot/penalties.py").read_text()
    assert '("insult_sa", "⚠️ Оскорбление сотрудников SA / поведение против стандартов клуба", Decimal("500"), False, False)' in text
    assert 'is_repeat_dismissal = code == "insult_sa" and previous > 0' in text
    assert 'dismissal_required=(premium or is_repeat_dismissal)' in text
    assert 'premium_reduction_percent=100 if (premium or is_repeat_dismissal) else 0' in text

def test_penalty_back_callback_exists():
    text = Path("app/bot/penalties.py").read_text()
    assert 'F.data == "penalty_close"' in text
    assert 'reply_markup=admins_menu()' in text


def test_manual_penalty_ui_selects_employee_before_rule_and_never_requests_employee_id():
    text = Path("app/bot/penalties.py").read_text()
    assert 'callback_data=f"penalty_employee:{employee.id}"' in text
    assert 'Технические ID сотрудника здесь не используются.' in text
    assert 'Введите комментарий к нарушению. Одной строкой, без ID сотрудника.' in text
    assert 'EMPLOYEE_ID | комментарий' not in text


def test_manual_penalty_requires_confirmation_before_create():
    text = Path("app/bot/penalties.py").read_text()
    assert 'callback_data="penalty_confirm"' in text
    assert 'callback_data="penalty_cancel"' in text
    assert 'await state.set_state(PenaltyState.confirming)' in text
    assert 'await create_manual_penalty(callback.from_user.id, employee_id, code, comment)' in text


def test_manual_penalty_confirmation_shows_admin_rule_and_consequence():
    text = Path("app/bot/penalties.py").read_text()
    assert '👤 Администратор:' in text
    assert '⚠️ Нарушение:' in text
    assert '💰 Последствие:' in text
    assert '📝 Комментарий:' in text


def test_premium_rules_require_dismissal():
    text = Path("app/bot/penalties.py").read_text()
    assert 'dismissal_required=(premium or is_repeat_dismissal)' in text
    assert '"100% премии за расчётный период + увольнение"' in text
