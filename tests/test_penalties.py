from pathlib import Path


def test_penalty_catalog_contains_approved_fixed_policy_codes():
    text = Path("app/bot/penalties.py").read_text()
    for code in [
        "collection_guest_number", "telegram_report", "empty_fridge", "overflowing_bins", "sleeping_guest",
        "dirty_area", "late_request", "greeting", "smoking", "guest_drinks", "uniform", "entrance_trash",
        "cash_discipline", "secret_shopper", "game_update", "device_issue", "alcohol", "pc_restore",
        "work_phone", "insult_sa", "strangers", "commercial_break", "late_1h", "sleeping_admin",
        "discount_abuse", "no_show",
    ]:
        assert f'("{code}"' in text


def test_fixed_penalty_amounts_match_approved_policy():
    text = Path("app/bot/penalties.py").read_text()
    for code in [
        "collection_guest_number", "telegram_report", "empty_fridge", "overflowing_bins", "sleeping_guest",
        "dirty_area", "late_request", "greeting",
    ]:
        assert f'("{code}"' in text
        assert 'Decimal("250")' in text
    for code in [
        "smoking", "guest_drinks", "uniform", "entrance_trash", "cash_discipline", "secret_shopper",
        "game_update", "device_issue", "alcohol", "pc_restore", "work_phone", "insult_sa",
    ]:
        assert f'("{code}"' in text
        assert 'Decimal("500")' in text
    for code in ["strangers", "commercial_break", "late_1h", "sleeping_admin", "discount_abuse"]:
        assert f'("{code}"' in text
        assert 'Decimal("1000")' in text
    assert '("no_show"' in text
    assert 'Decimal("2000")' in text


def test_fixed_shift_pay_remains_2000():
    text = Path("app/bot/salary.py").read_text()
    assert 'SHIFT_PAY = Decimal("2000.00")' in text


def test_automatic_late_report_penalty_is_deduplicated():
    text = Path("app/bot/penalties.py").read_text()
    assert 'source_key = f"auto:telegram_report:{report.shift_id}"' in text
    assert 'SalaryViolation.source_key == source_key' in text


def test_insult_sa_policy_is_500_fixed_penalty():
    text = Path("app/bot/penalties.py").read_text()
    assert '("insult_sa", "Оскорбление сотрудников, гостей, поведение, не соответствующее стандартам клуба", Decimal("500"))' in text


def test_penalty_back_callback_exists():
    text = Path("app/bot/penalties.py").read_text()
    assert 'F.data == "penalty_close"' in text
    assert 'reply_markup=admins_menu()' in text


def test_manual_penalty_ui_selects_employee_before_rule():
    text = Path("app/bot/penalties.py").read_text()
    assert 'callback_data=f"penalty_employee:{e.id}"' in text
    assert 'Выберите администратора:' in text
    assert 'EMPLOYEE_ID | комментарий' not in text


def test_manual_penalty_requires_confirmation_before_create():
    text = Path("app/bot/penalties.py").read_text()
    assert 'callback_data="penalty_confirm"' in text
    assert 'callback_data="penalty_cancel"' in text
    assert 'await state.set_state(PenaltyState.confirming)' in text
    assert 'await create_manual_penalty(callback.from_user.id, employee_id, code, comment)' in text


def test_manual_penalty_confirmation_shows_admin_rule_and_comment():
    text = Path("app/bot/penalties.py").read_text()
    assert '🧾 <b>Проверьте начисление</b>' in text
    assert "👤 {data.get('penalty_employee_name')}" in text
    assert '⚠️ {title}' in text
    assert '💰 {amount:.0f} ₽' in text
    assert '📝 {comment[:1000]}' in text
