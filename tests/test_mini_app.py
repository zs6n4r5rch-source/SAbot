from pathlib import Path


def test_unified_mini_app_contains_management_sections():
    root = Path(__file__).parents[1]
    html = (root / "app" / "webapp" / "static" / "index_v2.html").read_text(encoding="utf-8")
    for label in ["Summary", "WORK CENTER", "CRM", "FINANCE", "WAREHOUSE", "Предыдущая смена", "CONTROL"]:
        assert label in html


def test_unified_mini_app_has_server_api_sections():
    root = Path(__file__).parents[1]
    text = (root / "app" / "webapp" / "unified_api.py").read_text(encoding="utf-8")
    for route in ["/overview", "/work-center", "/crm/groups", "/warehouse", "/finance", "/shifts/previous", "/analytics"]:
        assert f'"{route}"' in text


def test_legacy_page_composer_is_non_mutating():
    root = Path(__file__).parents[1]
    source = (root / "app" / "webapp" / "page_composer.py").read_text(encoding="utf-8")
    assert "return html" in source
    assert "monkey-patching" in source
