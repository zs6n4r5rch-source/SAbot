from pathlib import Path


def test_admin_shift_control_is_installed():
    main = Path("app/main.py").read_text(encoding="utf-8")
    module = Path("app/webapp/admin_shift_control.py").read_text(encoding="utf-8")
    assert "install_admin_shift_control(web_app)" in main
    assert '"/api/admins/{employee_id}/shifts"' in module
    assert "reports_submitted" in module
    assert "Сейчас на смене" in module
    assert "adminDetail" in module
