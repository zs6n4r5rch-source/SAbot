from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_virtual_telegram_harness_covers_real_security_layers():
    path = ROOT / "tests" / "virtual_telegram" / "test_rbac_e2e.py"
    text = path.read_text(encoding="utf-8")
    assert "validate_init_data" not in text  # it must exercise the real endpoint, not bypass it
    assert "X-Telegram-Init-Data" in text
    assert "test_tampered_init_data_is_rejected" in text
    assert "test_admin_never_sees_salary_even_with_shift_permission" in text
    assert "test_owner_preview_is_authorized_but_does_not_change_actual_identity" in text


def test_frontend_admin_menu_does_not_advertise_owner_only_sections():
    text = (ROOT / "app" / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    marker = "if(state.role==='admin')return ["
    start = text.index(marker)
    end = text.index("].indexOf(p)>=0", start)
    admin_allowlist = text[start:end]
    assert "'salary'" not in admin_allowlist
    assert "'penalties'" not in admin_allowlist
    assert "'admin'" not in admin_allowlist
    assert "'profiles'" not in admin_allowlist
    assert "'settings'" not in admin_allowlist


def test_frontend_admin_sections_match_server_rbac_allowlist():
    text = (ROOT / "app" / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    marker = "if(state.role==='admin')return ["
    start = text.index(marker)
    end = text.index("].indexOf(p)>=0", start)
    admin_allowlist = text[start:end]
    expected = [
        "'overview'", "'work'", "'warehouse'", "'shifts'",
        "'warehouseCritical'", "'warehouseCategories'", "'warehouseArrivals'",
        "'warehouseSales'", "'warehouseHistory'", "'warehouseWriteoffs'",
        "'warehouseInventories'", "'warehouseDiscrepancies'",
    ]
    for item in expected:
        assert item in admin_allowlist
