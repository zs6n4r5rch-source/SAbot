from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_final_contract_router_is_authoritative_before_legacy_unified_router():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "web_app.include_router(final_contract_router)" in src
    assert src.index("web_app.include_router(final_contract_router)") < src.index("web_app.include_router(unified_api_router)")
    assert "install_admin_shift_control" not in src


def test_admin_subject_scoping_exists_for_sensitive_operational_contours():
    src = (ROOT / "app/webapp/final_contract_api.py").read_text(encoding="utf-8")
    assert "stmt = stmt.where(Shift.employee_id == user.employee_id)" in src
    assert "stmt = stmt.where(ShiftCloseReport.employee_id == user.employee_id)" in src
    assert "stmt = stmt.where(SalaryViolation.employee_id == user.employee_id)" in src
    assert "stmt = stmt.where(SalaryPeriod.employee_id == user.employee_id)" in src


def test_smm_can_use_crm_and_campaign_contract_without_finance_permission():
    src = (ROOT / "app/webapp/final_contract_api.py").read_text(encoding="utf-8")
    assert 'user.role == "smm"' in src
    assert "Permission.AUDIENCE" in src
    assert "Permission.CAMPAIGNS" in src
    assert '@router.post("/smm/campaigns")' in src
    assert '@router.post("/smm/campaigns/{campaign_id}/send")' in src
    assert '@router.post("/smm/campaigns/{campaign_id}/schedule")' in src


def test_guest_contour_uses_authenticated_link_and_langame_read_only_data():
    src = (ROOT / "app/webapp/final_contract_api.py").read_text(encoding="utf-8")
    assert 'GuestTelegram.telegram_user_id == user.telegram_id' in src
    assert "langame_client.guest_by_id" in src
    assert "langame_client.guest_sessions" in src


def test_smm_surface_is_loaded_without_reintroducing_dom_mutation_observer():
    src = (ROOT / "app/webapp/static/design-v2.js").read_text(encoding="utf-8")
    assert "MutationObserver" not in src
    assert "smm-actions.js" in src
