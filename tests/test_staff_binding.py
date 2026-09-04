from app.models import UserRole
from app.services.staff_access import REAL_STAFF, normalize_username


def test_real_staff_roster_contains_expected_profiles():
    assert [(n, u, r) for n, u, r in REAL_STAFF] == [
        ("Эдуард", "edonly_one", UserRole.OWNER.value),
        ("Данил", "grda8", UserRole.OWNER.value),
        ("Анатолий", "nemanikhin", UserRole.OWNER.value),
        ("Иван", "Kenchik1786", UserRole.ADMIN.value),
        ("Анастасия", "nasyanasikova", UserRole.ADMIN.value),
        ("Вячеслав", "imapolzovatela28", UserRole.ADMIN.value),
        ("Юрий", "sigillcoree", UserRole.ADMIN.value),
    ]


def test_username_normalization():
    assert normalize_username("@Kenchik1786") == "kenchik1786"
    assert normalize_username(" nasyanasikova ") == "nasyanasikova"
