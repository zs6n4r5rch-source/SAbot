from pathlib import Path

MODULE = Path(__file__).parents[1] / "app" / "webapp" / "bar_finance.py"
APP = Path(__file__).parents[1] / "app" / "webapp" / "app.py"
UI = Path(__file__).parents[1] / "app" / "webapp" / "static" / "index_v2.html"


def test_bar_finance_uses_langame_sales_and_arrivals():
    source = MODULE.read_text()
    assert "langame_client.product_sales" in source
    assert "langame_client.product_arrivals" in source
    assert "products/expense" in source
    assert "products/arrival" in source
    assert '"profit"' in source
    assert "sales - purchases" in source


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


def test_unified_mini_app_has_finance_entrypoint():
    source = UI.read_text()
    assert "api('finance" in source
    assert "FINANCE" in source
    assert "Себестоимость" in source
    assert "Прибыль" in source
