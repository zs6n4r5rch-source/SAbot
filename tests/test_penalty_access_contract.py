from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_penalty_api_is_owner_only_and_supports_manual_creation():
    source = (ROOT / "app" / "webapp" / "penalties_api.py").read_text()
    assert 'user.role != "owner"' in source
    assert '@router.post("")' in source
    assert 'create_manual_penalty' in source


def test_mini_app_admin_does_not_have_penalty_route():
    source = (ROOT / "app" / "webapp" / "static" / "app-guard.js").read_text()
    assert "'penalties'" in source  # owner route remains available
    assert "user.role" not in source  # role is represented by state.role in this shell
    # The admin permission contract is asserted directly by the current can() expression.
    marker = "if(r==='admin')return ["
    start = source.index(marker)
    end = source.index("].includes(p)", start)
    assert "'penalties'" not in source[start:end]
