from pathlib import Path


def test_admin_shift_control_is_installed_in_active_contract():
    root = Path("app/webapp")
    main = Path("app/main.py").read_text(encoding="utf-8")
    contract = (root / "final_contract_api.py").read_text(encoding="utf-8")
    assert "final_contract_router" in main
    assert '@router.get("/shifts")' in contract
    assert "Shift.employee_id == user.employee_id" in contract
    assert '@router.get("/shifts/previous")' in contract
    assert '@router.get("/shifts/close-reports")' in contract
    assert '@router.get("/salary")' in contract
