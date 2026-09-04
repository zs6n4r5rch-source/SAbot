from pathlib import Path


def test_cleaning_state_exists_before_transition():
    text = Path('app/bot/shift_closing.py').read_text()
    assert 'waiting_cleaning = State()' in text
    assert 'state.set_state(ShiftCloseState.waiting_cleaning)' in text


def test_repeat_penalty_counts_prior_same_rule_regardless_of_source():
    text = Path('app/bot/penalties.py').read_text()
    assert 'SalaryViolation.employee_id == employee_id, SalaryViolation.rule_code == code)) if (repeat or code == \"insult_sa\") else 0' in text
    assert 'SalaryViolation.source == "manual"' not in text

def test_global_cancel_is_scoped_to_admin_link_fsm():
    text = Path('app/bot/handlers.py').read_text()
    assert '@router.message(Command("cancel"), AdminLinkState.waiting_telegram_id)' in text
    assert '@router.message(Command("cancel"), AdminLinkState.waiting_employee_id)' in text
    assert '@router.message(Command("cancel"))\nasync def cancel_link' not in text
