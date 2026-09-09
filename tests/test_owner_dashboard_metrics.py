from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_authoritative_owner_dashboard_is_registered_before_legacy_unified_router():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "web_app.include_router(owner_dashboard_router)" in src
    assert src.index("web_app.include_router(owner_dashboard_router)") < src.index("web_app.include_router(unified_api_router)")


def test_authoritative_dashboard_separates_till_and_product_sales():
    src = (ROOT / "app/webapp/owner_dashboard_api.py").read_text(encoding="utf-8")
    assert '"till": till' in src
    assert '"products": products' in src
    assert '"total": till' in src
    assert '"cashflow"' in src
    assert '"source_note"' in src


def test_authoritative_dashboard_uses_local_day_policy_for_today():
    src = (ROOT / "app/webapp/owner_dashboard_api.py").read_text(encoding="utf-8")
    assert "local_day_bounds()" in src
    assert "timezone_name()" in src
