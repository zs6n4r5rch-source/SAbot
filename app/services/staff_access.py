from sqlalchemy import select

from app.models import AccessProfile, Employee, UserRole


def normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.lower().replace("@", "").strip()


# Canonical staff roster. These profiles are provisioned on startup/first /start.
REAL_STAFF = [
    ("Эдуард", "edonly_one", UserRole.OWNER.value),
    ("Данил", "grda8", UserRole.OWNER.value),
    ("Анатолий", "nemanikhin", UserRole.OWNER.value),
    ("Иван", "Kenchik1786", UserRole.ADMIN.value),
    ("Анастасия", "nasyanasikova", UserRole.ADMIN.value),
    ("Вячеслав", "imapolzovatela28", UserRole.ADMIN.value),
    ("Юрий", "sigillcoree", UserRole.ADMIN.value),
]


async def ensure_real_staff_profiles(session):
    """Ensure every configured staff member has an active AccessProfile."""
    created = 0
    for display_name, username, role in REAL_STAFF:
        username = normalize_username(username)
        profile = (await session.execute(
            select(AccessProfile).where(AccessProfile.username == username)
        )).scalar_one_or_none()
        if profile is None:
            profile = AccessProfile(
                display_name=display_name,
                username=username,
                role=role,
                active=True,
            )
            session.add(profile)
            created += 1
        else:
            profile.display_name = display_name
            profile.role = role
            profile.active = True
    return created


async def ensure_staff_profile(session, username: str):
    key = normalize_username(username)
    for display_name, roster_username, role in REAL_STAFF:
        if normalize_username(roster_username) != key:
            continue
        profile = (await session.execute(
            select(AccessProfile).where(AccessProfile.username == key)
        )).scalar_one_or_none()
        if profile is None:
            profile = AccessProfile(
                display_name=display_name,
                username=key,
                role=role,
                active=True,
            )
            session.add(profile)
        else:
            profile.display_name = display_name
            profile.role = role
            profile.active = True
        await session.flush()
        return profile
    return None


async def match_admin_profiles_to_employees(session):
    profiles = (await session.execute(
        select(AccessProfile).where(
            AccessProfile.active.is_(True),
            AccessProfile.role == UserRole.ADMIN.value,
        )
    )).scalars().all()
    employees = (await session.execute(
        select(Employee).where(Employee.active.is_(True))
    )).scalars().all()
    updated = 0
    for profile in profiles:
        if profile.employee_id:
            continue
        pname = (profile.display_name or "").lower().strip()
        matched = []
        for employee in employees:
            name = (employee.full_name or "").lower().strip()
            if name and pname and (name == pname or name in pname or pname in name):
                matched.append(employee)
        if len(matched) == 1:
            profile.employee_id = matched[0].id
            updated += 1
    return updated
