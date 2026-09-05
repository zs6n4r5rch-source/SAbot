from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_menu_state_reset_covers_problematic_navigation_buttons():
    src = (ROOT / "app/bot/menu_state.py").read_text(encoding="utf-8")
    for label in (
        "📊 Ежедневный отчёт",
        "⚠️ Расхождения",
        "⚙️ Минимальные остатки",
        "📣 Рассылки",
        "↩️ Назад",
    ):
        assert label in src
    assert "await state.clear()" in src


def test_owner_inline_menu_does_not_expose_legacy_fines_label():
    src = (ROOT / "app/bot/inline_keyboards.py").read_text(encoding="utf-8")
    assert '"⚠️ Нарушения", "owner:penalties"' in src
    assert '"⚠️ Штрафы", "owner:penalties"' not in src


def test_all_owner_webapp_shortcuts_point_to_existing_static_pages():
    keyboard = (ROOT / "app/bot/inline_keyboards.py").read_text(encoding="utf-8")
    static = ROOT / "app/webapp/static"
    for page in ("broadcasts.html", "statistics.html", "guests.html", "social.html", "advertising.html"):
        assert (static / page).exists(), page
        assert f"/static/{page}" in keyboard
