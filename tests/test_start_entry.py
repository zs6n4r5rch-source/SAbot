from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_start_handler_exists_and_clears_state_before_routing():
    src = (ROOT / "app/bot/start.py").read_text(encoding="utf-8")
    assert "@router.message(CommandStart())" in src
    assert "await state.clear()" in src
    assert "user = await get_access(message)" in src
    assert "reply_markup=admin_inline_menu" in src
    assert "reply_markup=owner_inline_menu" in src


def test_canonical_start_router_is_registered_before_legacy_handlers():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "from app.bot.start import router as start_router" in src
    assert "dp.include_router(start_router)" in src
    assert src.index("dp.include_router(start_router)") < src.index("dp.include_router(router)")
