from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.db.session import SessionLocal
from app.models import AccessProfile, TelegramUser, UserRole
from app.webapp.app import app as web_app
from app.webapp.auth_api import router as auth_router
from app.webapp.rbac_middleware import UnifiedRBACMiddleware
from app.webapp.unified_api import router as unified_router

TEST_TG_OWNER = 900_000_001
TEST_TG_ADMIN = 900_000_002
TEST_TG_SMM = 900_000_003
TEST_TG_GUEST = 900_000_004
TEST_TG_UNKNOWN = 900_000_005


def make_init_data(telegram_id: int, username: str = "", first_name: str = "Test") -> str:
    user = {"id": telegram_id, "first_name": first_name, "username": username}
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "virtual_harness",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(
        b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
    ).digest()
    pairs["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(pairs)


@pytest.fixture(scope="session", autouse=True)
def wire_app_like_production():
    mounted = {getattr(r, "path", None) for r in web_app.routes}
    if "/api/app/overview" not in mounted:
        web_app.include_router(unified_router)
    if "/api/app/auth" not in mounted:
        web_app.include_router(auth_router)
    if not any(
        getattr(m, "cls", None) is UnifiedRBACMiddleware
        for m in getattr(web_app, "user_middleware", [])
    ):
        web_app.add_middleware(UnifiedRBACMiddleware)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=web_app)
    async with AsyncClient(
        transport=transport, base_url="http://virtual-tg-harness"
    ) as c:
        yield c


@pytest_asyncio.fixture(scope="module", autouse=True)
async def seed_and_clean_access_profiles():
    usernames = ["virtualtestowner", "virtualtestadmin", "virtualtestsmm"]
    ids = [TEST_TG_OWNER, TEST_TG_ADMIN, TEST_TG_SMM, TEST_TG_GUEST, TEST_TG_UNKNOWN]
    async with SessionLocal() as session:
        await session.execute(delete(TelegramUser).where(TelegramUser.telegram_id.in_(ids)))
        await session.execute(delete(AccessProfile).where(AccessProfile.username.in_(usernames)))
        await session.commit()
        session.add_all(
            [
                AccessProfile(username="virtualtestowner", role=UserRole.OWNER.value, active=True),
                AccessProfile(username="virtualtestadmin", role=UserRole.ADMIN.value, active=True),
                AccessProfile(username="virtualtestsmm", role=UserRole.SMM.value, active=True),
            ]
        )
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(TelegramUser).where(TelegramUser.telegram_id.in_(ids)))
        await session.execute(delete(AccessProfile).where(AccessProfile.username.in_(usernames)))
        await session.commit()


async def authed_headers(client, telegram_id: int, role: str, username: str = ""):
    init_data = make_init_data(telegram_id, username=username)
    response = await client.get(
        "/api/app/auth",
        params={"role": role},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert response.status_code == 200, (
        f"auth as {role} failed: {response.status_code} {response.text}"
    )
    return {"X-Telegram-Init-Data": init_data}


ROLE_SECTIONS = {
    "owner": ["/overview", "/work-center", "/crm", "/warehouse", "/shifts", "/penalties", "/salary", "/analytics", "/settings"],
    "admin": ["/overview", "/work-center", "/warehouse", "/shifts", "/bonuses"],
    "smm": ["/overview", "/crm", "/smm/campaigns"],
}
ALL_SECTIONS = sorted(
    {section for sections in ROLE_SECTIONS.values() for section in sections}
    | {"/salary", "/analytics", "/penalties", "/settings", "/admin/profiles"}
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,tg_id,username",
    [
        ("owner", TEST_TG_OWNER, "virtualtestowner"),
        ("admin", TEST_TG_ADMIN, "virtualtestadmin"),
        ("smm", TEST_TG_SMM, "virtualtestsmm"),
    ],
)
async def test_role_can_only_reach_its_own_sections(client, role, tg_id, username):
    headers = await authed_headers(client, tg_id, role, username)
    for section in ALL_SECTIONS:
        response = await client.get(f"/api/app{section}", headers=headers)
        should_allow = section in ROLE_SECTIONS[role]
        if should_allow:
            assert response.status_code != 403, (
                f"{role} was denied {section}: {response.status_code} {response.text}"
            )
        else:
            assert response.status_code == 403, (
                f"{role} was allowed {section}: {response.status_code} {response.text}"
            )


@pytest.mark.asyncio
async def test_admin_never_sees_salary_even_with_shift_permission(client):
    headers = await authed_headers(client, TEST_TG_ADMIN, "admin", "virtualtestadmin")
    response = await client.get("/api/app/salary", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_preview_is_authorized_but_does_not_change_actual_identity(client):
    init_data = make_init_data(TEST_TG_OWNER, username="virtualtestowner", first_name="Owner")
    response = await client.get(
        "/api/app/auth",
        params={"role": "admin"},
        headers={"X-Telegram-Init-Data": init_data},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["actual_role"] == "owner"
    assert body["preview"] is True


@pytest.mark.asyncio
async def test_guest_role_never_requires_a_staff_binding(client):
    headers = await authed_headers(client, TEST_TG_GUEST, "guest")
    response = await client.get("/api/app/guest/me", headers=headers)
    assert response.status_code in (200, 404), response.text


@pytest.mark.asyncio
async def test_unbound_telegram_user_cannot_claim_staff_role(client):
    headers = {"X-Telegram-Init-Data": make_init_data(TEST_TG_UNKNOWN, username="nobody_bound")}
    response = await client.get("/api/app/auth", params={"role": "owner"}, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tampered_init_data_is_rejected(client):
    good = make_init_data(TEST_TG_ADMIN, username="virtualtestadmin")
    tampered = good.replace(str(TEST_TG_ADMIN), str(TEST_TG_OWNER), 1)
    response = await client.get("/api/app/auth", params={"role": "owner"}, headers={"X-Telegram-Init-Data": tampered})
    assert response.status_code == 401
