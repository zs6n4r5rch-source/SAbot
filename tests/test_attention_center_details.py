from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_attention_center_exposes_actionable_stock_details():
    src = (ROOT / "app/webapp/p1_routes.py").read_text(encoding="utf-8")
    assert "select(InventoryBalance, Product)" in src
    assert '"product_id": product.id' in src
    assert '"product": product.name' in src
    assert '"quantity": dec(balance.quantity)' in src
    assert '"min_stock": dec(balance.min_stock)' in src
