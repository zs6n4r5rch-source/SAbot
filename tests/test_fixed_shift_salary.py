from decimal import Decimal
from pathlib import Path


def test_salary_uses_fixed_shift_pay():
    source = Path(__file__).parents[1] / "app" / "bot" / "salary.py"
    text = source.read_text()
    assert 'SHIFT_PAY = Decimal("2000.00")' in text
    assert 'Decimal(len(shifts)) * rate' in text
    assert 'Оплата за смену' in text
