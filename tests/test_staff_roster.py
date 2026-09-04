from app.models import UserRole
from app.services.staff_access import REAL_STAFF, normalize_username

def test_owner_roster():
    roster = {normalize_username(u): r for _, u, r in REAL_STAFF}
    assert roster["edonly_one"] == UserRole.OWNER.value
    assert roster["grda8"] == UserRole.OWNER.value
    assert roster["nemanikhin"] == UserRole.OWNER.value

def test_all_expected_staff_present():
    usernames = {normalize_username(u) for _, u, _ in REAL_STAFF}
    assert {"edonly_one", "grda8", "nemanikhin", "kenchik1786", "nasyanasikova", "imapolzovatela28", "sigillcoree"} <= usernames
