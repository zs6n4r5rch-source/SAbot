from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_admin_cannot_access_salary_or_penalties_at_middleware_boundary():
    source = (ROOT / "app" / "webapp" / "rbac_middleware.py").read_text()
    assert 'if path=="/api/app/salary" and role!="owner":' in source
    assert 'if path=="/api/app/penalties" and role!="owner":' in source
    assert '"/bonuses"' in source


def test_admin_penalty_ui_contract_is_denied():
    ui = (ROOT / "app" / "webapp" / "static" / "app-guard.js").read_text()
    assert "if(r==='admin')return ['overview','work','warehouse'" in ui
    assert "'penalties'" not in ui.split("if(r==='admin')",1)[1].split("if(r==='smm')",1)[0]
