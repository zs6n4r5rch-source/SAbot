"""Virtual Telegram Mini App authorization tests.

The suite signs synthetic Telegram WebApp initData and exercises the real
FastAPI ASGI app in-process. It uses a disposable PostgreSQL database and
never starts Telegram polling.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx
import pytest

from app.db.session import SessionLocal
from app.models import AccessProfile, TelegramUser, UserRole


USERS = {
    "owner": (900000001, "virtualtestowner"),
    "admin": (900000002, "virtualtestadmin"),
    "smm": (900000003, "virtualtestsmm"),
    "guest": (900000004, None),
    "unknown": (900000005, None),
}

ROLE_SECTIONS = {
    "owner": {"overview", "work-center", "crm", "warehouse", "shifts", "penalties", "salary", "analytics", "settings", "bonuses"},
    "admin": {"overview", "work-center", "warehouse", "shifts", "bonuses"},
    "smm": {"overview", "crm"},
    "guest": {"guest/me"},
}


def make_init_data(bot_token: str, telegram_id: int, username: str | None = None) -> str:
    user = {"id": telegram_id, "first_name": "Virtual", "last_name": "User"}
    if username:
        user["username"] = username
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": f"virtual-{telegram_id}",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def _seed_users() -> None:
    async def seed():
        async with SessionLocal() as session:
            for telegram_id, username in USERS.values():
                await session.execute(TelegramUser.__table__.delete().where(TelegramUser.telegram_id == telegram_id))
            for username in (USERS["owner"][1], USERS["admin"][1], USERS["smm"][1]):
                await session.execute(AccessProfile.__table__.delete().where(AccessProfile.username == username))
            session.add_all([
                AccessProfile(display_name="Virtual Owner", username=USERS["owner"][1], role=UserRole.OWNER.value, active=True),
                AccessProfile(display_name="Virtual Admin", username=USERS["admin"][1], role=UserRole.ADMIN.value, active=True),
                AccessProfile(display_name="Virtual SMM", username=USERS["smm"][1], role=UserRole.SMM.value, active=True),
            ])
            await session.commit()
    asyncio.run(seed())


def _cleanup_users() -> None:
    async def cleanup():
        async with SessionLocal() as session:
            for telegram_id, _ in USERS.values():
                await session.execute(TelegramUser.__table__.delete().where(TelegramUser.telegram_id == telegram_id))
            for username in (USERS["owner"][1], USERS["admin"][1], USERS["smm"][1]):
                await session.execute(AccessProfile.__table__.delete().where(AccessProfile.username == username))
            await session.commit()
    asyncio.run(cleanup())


@pytest.fixture(scope="module", autouse=True)
def seeded_database():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for virtual Telegram RBAC tests")
    _seed_users()
    yield
    _cleanup_users()


@pytest.fixture(scope="module")
def app_client():
    from app.webapp.app import app
    from app.webapp.rbac_middleware import UnifiedRBACMiddleware
    if not any(m.cls is UnifiedRBACMiddleware for m in app.user_middleware):
        app.add_middleware(UnifiedRBACMiddleware)
    return app


@pytest.fixture(scope="module")
def bot_token():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        pytest.skip("TELEGRAM_BOT_TOKEN is required for signed initData tests")
    return token


def request(app, method, path, bot_token, role, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, headers={"X-Telegram-Init-Data": make_init_data(bot_token, *USERS[role])}, **kwargs)
    return asyncio.run(run())


def test_tampered_init_data_is_rejected(app_client, bot_token):
    init_data = make_init_data(bot_token, *USERS["owner"]) + "x"
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_client), base_url="http://testserver") as client:
            return await client.get("/api/app/auth", params={"role": "owner"}, headers={"X-Telegram-Init-Data": init_data})
    assert asyncio.run(run()).status_code == 401


def test_unbound_user_cannot_claim_staff_role(app_client, bot_token):
    response = request(app_client, "GET", "/api/app/auth?role=admin", bot_token, "unknown")
    assert response.status_code == 403


def test_unbound_guest_does_not_require_staff_binding(app_client, bot_token):
    response = request(app_client, "GET", "/api/app/auth?role=guest", bot_token, "guest")
    assert response.status_code == 200
    assert response.json()["role"] == "guest"


def test_owner_can_preview_admin_shape(app_client, bot_token):
    response = request(app_client, "GET", "/api/app/auth?role=admin", bot_token, "owner")
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["actual_role"] == "owner"
    assert body["preview"] is True


def test_role_sections_follow_current_contract(app_client, bot_token):
    endpoints = {
        "overview": "/api/app/overview",
        "work-center": "/api/app/work-center",
        "crm": "/api/app/crm",
        "warehouse": "/api/app/warehouse",
        "shifts": "/api/app/shifts/previous",
        "penalties": "/api/app/penalties",
        "salary": "/api/app/salary",
        "analytics": "/api/app/analytics",
        "settings": "/api/app/settings",
        "bonuses": "/api/app/bonuses",
        "guest/me": "/api/app/guest/me",
    }
    for role, allowed in ROLE_SECTIONS.items():
        for section, path in endpoints.items():
            response = request(app_client, "GET", path, bot_token, role)
            if section in allowed:
                assert response.status_code != 403, (role, section, response.text)
            else:
                assert response.status_code == 403, (role, section, response.text)


def test_admin_never_sees_salary_or_penalties(app_client, bot_token):
    for path in ("/api/app/salary", "/api/app/penalties"):
        assert request(app_client, "GET", path, bot_token, "admin").status_code == 403


def test_admin_is_operational_only(app_client, bot_token):
    for path in ("/api/app/crm", "/api/app/settings", "/api/app/admin/profiles", "/api/app/salary", "/api/app/penalties"):
        assert request(app_client, "GET", path, bot_token, "admin").status_code == 403
