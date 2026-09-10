from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "app" / "webapp" / "bar_finance.py"
APP = ROOT / "app" / "webapp" / "app.py"
UI = ROOT / "app" / "webapp" / "static" / "index.html"
LIVE_UI = ROOT / "app" / "webapp" / "static" / "app-ux-v10.js"


def test_bar_finance_uses_langame_sales_and_arrivals():
    source = MODULE.read_text()
    assert "langame_client.product_sales" in source
    assert "langame_client.product_arrivals" in source
    assert "products/expense" in source
    assert "products/arrival" in source
    assert '"profit"' in source


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


def test_production_finance_screen_has_economics_entrypoint():
    shell = UI.read_text()
    live = LIVE_UI.read_text()
    assert "/api/app/finance" in shell
    assert "Себестоимость" in live
    assert "Прибыль" in live
