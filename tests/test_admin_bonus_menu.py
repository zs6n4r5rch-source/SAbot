from pathlib import Path


def test_admin_menu_has_bonus_section():
    text = Path('app/bot/keyboards.py').read_text()
    assert '🏆 Мои бонусы' in text


def test_bonus_dashboard_separates_earned_and_conditional():
    text = Path('app/bot/salary.py').read_text()
    assert 'УЖЕ ЗАРАБОТАНО / ЗАФИКСИРОВАНО' in text
    assert 'БОНУСЫ ПО УСЛОВИЯМ' in text
    assert 'ℹ️ Месячные бонусы окончательно начисляются' in text


def test_owner_menu_has_bonus_section():
    text = Path('app/bot/keyboards.py').read_text()
    assert '🏆 Бонусы' in text

def test_owner_bonus_dashboard_exists():
    text = Path('app/bot/salary.py').read_text()
    assert 'async def _owner_bonus_dashboard' in text
    assert 'Зафиксировано в расчётах' in text
    assert 'Потенциал по текущим условиям' in text
    assert 'Администраторов с нарушениями' in text
