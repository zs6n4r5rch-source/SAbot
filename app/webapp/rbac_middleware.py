from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Guest, InventoryBalance, Shift
from app.webapp.app import current_user


# Supported unified roles: "owner", "admin", "smm", "guest".
ROLE_PATHS = {
    "owner": None,
    "admin": ("/overview", "/work-center", "/crm", "/warehouse", "/shifts", "/penalties", "/salary", "/admin/", "/settings"),
    "smm": ("/overview", "/crm", "/smm/"),
    "guest": ("/guest/",),
}


async def safe_overview(role: str):
    async with SessionLocal() as session:
        if role == "admin":
            critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
            open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
            return {
                "role": role,
                "timezone": None,
                "revenue": {"products": None, "gaming": None, "other": None, "total": None, "product_units": None},
                "attention": ([{"key": "critical_stock", "count": critical, "title": "Критический склад", "target": "warehouse"}] if critical else []),
                "kpi": {"guests": None, "new_guests": None, "average_check": None, "open_shifts": open_shifts},
                "source_status": {"langame": "limited_by_role"},
            }
        guests = await session.scalar(select(func.count(Guest.id))) or 0
        return {
            "role": role,
            "timezone": None,
            "revenue": {"products": None, "gaming": None, "other": None, "total": None, "product_units": None},
            "attention": [],
            "kpi": {"guests": guests, "new_guests": None, "average_check": None, "open_shifts": None},
            "source_status": {"langame": "marketing_contour"},
        }


class UnifiedRBACMiddleware:
    """Backend guard for the unified Mini App contour.

    Endpoint-level permissions remain authoritative, while this middleware also
    prevents a role from directly reaching a section outside its approved UI
    contour. This is intentionally stricter than frontend navigation so hidden
    routes cannot be reached by hand-crafted requests.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.startswith("/api/app/"):
            await self.app(scope, receive, send)
            return
        if path == "/api/app/auth":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        try:
            user, _ = await current_user(request)
            role = str(getattr(user, "role", "")).lower()
        except Exception:
            role = ""
        if role not in ROLE_PATHS:
            response = JSONResponse({"detail": "Unified API role is not configured"}, status_code=403)
            await response(scope, receive, send)
            return
        allowed = ROLE_PATHS[role]
        if allowed is not None and not any(path.startswith("/api/app" + prefix) for prefix in allowed):
            response = JSONResponse({"detail": "Раздел недоступен для этой роли"}, status_code=403)
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["unified_role"] = role
        if path == "/api/app/overview" and role in {"admin", "smm"}:
            response = JSONResponse(await safe_overview(role), status_code=200)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
