from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Guest, InventoryBalance, Shift
from app.services.langame import LangameAPIError
from app.webapp.app import current_user
from app.webapp.langame_live import warehouse_arrivals, warehouse_items, warehouse_sales

ROLE_PATHS = {
    "owner": None,
    "admin": ("/overview", "/work-center", "/crm", "/warehouse", "/shifts", "/penalties", "/admin/", "/settings", "/live/"),
    "smm": ("/overview", "/crm", "/smm/", "/live/"),
    "guest": ("/guest/",),
}


async def safe_overview(role: str):
    async with SessionLocal() as session:
        if role == "admin":
            critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
            open_shifts = await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
            return {"role": role, "timezone": None, "revenue": {"products": None, "gaming": None, "other": None, "total": None, "product_units": None}, "attention": ([{"key": "critical_stock", "count": critical, "title": "Критический склад", "target": "warehouse"}] if critical else []), "kpi": {"guests": None, "new_guests": None, "average_check": None, "open_shifts": open_shifts}, "source_status": {"langame": "limited_by_role"}}
        guests = await session.scalar(select(func.count(Guest.id))) or 0
        return {"role": role, "timezone": None, "revenue": {"products": None, "gaming": None, "other": None, "total": None, "product_units": None}, "attention": [], "kpi": {"guests": guests, "new_guests": None, "average_check": None, "open_shifts": None}, "source_status": {"langame": "marketing_contour"}}


async def _live_data(path: str, role: str, request: Request):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    if path == "/api/app/warehouse":
        return await warehouse_items()
    if path == "/api/app/warehouse/critical":
        data = await warehouse_items()
        return {"source": "langame", "items": [x for x in data["items"] if x.get("critical")]}
    if path == "/api/app/warehouse/arrivals":
        days = min(max(int(request.query_params.get("days", "30")), 1), 365)
        return await warehouse_arrivals(days, now, now - timedelta(days=days))
    if path == "/api/app/warehouse/sales":
        days = min(max(int(request.query_params.get("days", "30")), 1), 365)
        return await warehouse_sales(days, now, now - timedelta(days=days))
    return None


class UnifiedRBACMiddleware:
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
        if path == "/api/app/salary" and role != "owner":
            response = JSONResponse({"detail": "Salary access is restricted to owner"}, status_code=403)
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
        if role in {"owner", "admin"} and path in {"/api/app/warehouse", "/api/app/warehouse/critical", "/api/app/warehouse/arrivals", "/api/app/warehouse/sales"}:
            try:
                response_data = await _live_data(path, role, request)
                if response_data is not None:
                    response = JSONResponse(response_data, status_code=200)
                    await response(scope, receive, send)
                    return
            except (LangameAPIError, ValueError) as exc:
                response = JSONResponse({"detail": f"LANGAME warehouse unavailable: {exc}"}, status_code=502)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
