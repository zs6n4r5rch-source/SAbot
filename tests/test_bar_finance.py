from pathlib import Path


MODULE = Path(__file__).parents[1] / "app" / "webapp" / "bar_finance.py"
APP = Path(__file__).parents[1] / "app" / "webapp" / "app.py"
UI = Path(__file__).parents[1] / "app" / "webapp" / "static" / "index.html"


def test_bar_finance_uses_langame_sales_and_arrivals():
    source = MODULE.read_text()
    assert "langame_client.product_sales" in source
    assert "langame_client.product_arrivals" in source
    assert "products/expense + products/arrival" in source
    assert '"profit": float(sales - purchases)' in source


def test_arrival_cost_supports_unit_and_total_purchase_values():
    source = MODULE.read_text()
    assert "price_purchase" in source
    assert "price_arrival" in source
    assert "purchase_price" in source
    assert '"sum", "amount", "total", "cost"' in source


def test_finance_endpoint_exposes_bar_block():
    source = APP.read_text()
    assert '@app.get("/api/bar-finance")' in source
    assert '"bar": bar' in source
    assert 'from app.webapp.bar_finance import report' in source


def test_mini_app_has_bar_period_switch_and_profit():
    source = UI.read_text()
    assert 'data-bar-days="1"' in source
    assert 'data-bar-days="7"' in source
    assert 'data-bar-days="30"' in source
    assert 'data-bar-days="90"' in source
    assert "Прибыль бара" in source
    assert "Приходы / закупка" in source
