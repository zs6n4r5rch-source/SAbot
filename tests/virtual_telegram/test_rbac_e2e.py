"""Virtual Telegram Mini App authorization tests.

These tests exercise the real FastAPI application in-process. No Telegram or
LANGAME network calls are intentionally made by the test itself; the suite
requires a disposable PostgreSQL database and should be run with LANGAME
access disabled/mocked in CI.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import httpx
import pytest


USERS = {
    "owner": (900000001, "virtualtestowner"),
    "admin": (900000002, "virtualtestadmin"),
    "smm": (900000003, "virtualtestsmm"),
    "guest": (900000004, None),
    "unknown": (900000005, None),
}

ROLE_SECTIONS = {
    "owner": {
        "overview", "work-center", "crm", "warehouse", "shifts", "penalties",
        "salary", "analytics", "settings", "bonuses",
    },
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
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


@pytest.fixture(scope="module")
def app_client():
    """Load the production ASGI app without starting Telegram polling."""
    from app.webapp.app import app
    from app.webapp.rbac_middleware import UnifiedRBACMiddleware

    # app.main normally installs this middleware. The direct fixture makes the
    # contract explicit while avoiding bot/scheduler startup during pytest.
    if not any(isinstance(m.cls, type) and m.cls is UnifiedRBACMiddleware for m in app.user_middleware):
        app.add_middleware(UnifiedRBACMiddleware)
    return app


@pytest.fixture(scope="module")
def bot_token():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        pytest.skip("TELEGRAM_BOT_TOKEN is required for signed initData tests")
    return token


@pytest.fixture
def client(app_client, bot_token):
    transport = httpx.ASGITransport(app=app_client)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def headers(bot_token, role):
    telegram_id, username = USERS[role]
    return {"X-Telegram-Init-Data": make_init_data(bot_token, telegram_id, username)}


@pytest.mark.asyncio
async def test_tampered_init_data_is_rejected(client, bot_token):
    h = headers(bot_token, "owner")
    h["X-Telegram-Init-Data"] += "x"
    response = await client.get("/api/app/auth", params={"role": "owner"}, headers=h)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unbound_user_cannot_claim_staff_role(client, bot_token):
    response = await client.get(
        "/api/app/auth", params={"role": "admin"}, headers=headers(bot_token, "unknown")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unbound_guest_does_not_require_staff_binding(client, bot_token):
    response = await client.get(
        "/api/app/auth", params={"role": "guest"}, headers=headers(bot_token, "guest")
    )
    assert response.status_code == 200
    assert response.json()["role"] == "guest"


@pytest.mark.asyncio
async def test_owner_can_preview_admin_shape(client, bot_token):
    response = await client.get(
        "/api/app/auth", params={"role": "admin"}, headers=headers(bot_token, "owner")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["actual_role"] == "owner"
    assert body["preview"] is True


@pytest.mark.asyncio
async def test_role_sections_follow_current_contract(client, bot_token):
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
            response = await client.get(path, headers=headers(bot_token, role))
            if section in allowed:
                assert response.status_code != 403, (role, section, response.text)
            else:
                assert response.status_code == 403, (role, section, response.text)


@pytest.mark.asyncio
async def test_admin_never_sees_salary_or_penalties(client, bot_token):
    for path in ("/api/app/salary", "/api/app/penalties"):
        response = await client.get(path, headers=headers(bot_token, "admin"))
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_is_operational_only(client, bot_token):
    forbidden = (
        "/api/app/crm",
        "/api/app/settings",
        "/api/app/admin/profiles",
        "/api/app/salary",
        "/api/app/penalties",
    )
    for path in forbidden:
        response = await client.get(path, headers=headers(bot_token, "admin"))
        assert response.status_code == 403
