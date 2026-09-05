from pathlib import Path


def test_attention_center_and_owner_shift_endpoints_exist():
    source = Path("app/webapp/p1_routes.py").read_text(encoding="utf-8")
    assert '@app.get("/api/attention-center")' in source
    assert '@app.get("/api/owner-shifts")' in source
    assert 'awaiting_shift_reports' in source
    assert 'cash_issues' in source
    assert 'dismissal_required' in source


def test_p2_renames_penalties_to_violations_and_surfaces_action_center():
    source = Path("app/webapp/p1_routes.py").read_text(encoding="utf-8")
    assert 'Штрафы · 30 дней' in source
    assert 'Нарушения · 30 дней' in source
    assert "'Штрафы'" in source
    assert "'Нарушения'" in source
    assert 'Открыть центр внимания' in source


def test_main_registers_p1_p2_routes():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert 'import app.webapp.p1_routes' in source
