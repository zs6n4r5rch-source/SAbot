from pathlib import Path


def test_smm_api_requires_smm_role_for_self_service():
    source = Path("app/webapp/smm_api.py").read_text(encoding="utf-8")
    assert 'user.role != UserRole.SMM.value' in source
    assert 'owner_allowed: bool = False' in source
    assert 'owner_allowed=True' in source


def test_smm_review_is_owner_only():
    source = Path("app/webapp/smm_api.py").read_text(encoding="utf-8")
    assert 'async def smm_review_task' in source
    assert 'smm_context(request, owner_allowed=True)' in source
    assert 'action not in ("approve", "reject")' in source
