from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_quality_router_is_registered_before_legacy_router():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "from app.bot.inventory_quality import router as inventory_quality_router" in src
    assert "dp.include_router(inventory_quality_router)" in src
    assert src.index("dp.include_router(inventory_quality_router)") < src.index("dp.include_router(router)")


def test_inventory_quality_resolves_local_product_names():
    src = (ROOT / "app/bot/inventory_quality.py").read_text(encoding="utf-8")
    assert "Product.langame_product_id.in_(ids)" in src
    assert "Товар LANGAME #" in src
    assert "Товар без ID" in src
