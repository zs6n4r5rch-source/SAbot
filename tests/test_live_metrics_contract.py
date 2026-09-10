import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_live_metrics_module_parses_and_uses_langame_sources():
    source = (ROOT / "app/webapp/live_metrics_api.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "langame_client.transactions" in source
    assert "langame_client.product_sales" in source
    assert "langame_client.guest_sessions" in source
    assert "langame_client.stock" in source
    assert "langame_client.guest_groups" in source
    assert "working_shift_id" in source
    assert "local_period_bounds" in source
    assert "local_month_bounds" in source
    assert 'period == "month"' in source


def test_smm_has_guest_read_permission_but_not_finance_permission():
    source = (ROOT / "app/permissions/core.py").read_text(encoding="utf-8")
    assert '"smm":' in source
    assert "Permission.GUESTS" in source
    assert "Permission.MANAGE_FINANCE" not in source.split('"smm":', 1)[1].split('"guest":', 1)[0]
