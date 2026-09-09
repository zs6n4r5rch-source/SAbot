from fastapi import Request
from fastapi.responses import JSONResponse
from app.webapp.app import current_user


ROLE_PATHS = {
    "owner": None,
    "admin": ("/overview", "/summary", "/work-center", "/crm", "/warehouse", "/shifts", "/penalties", "/salary", "/admin/", "/settings"),
    "smm": ("/overview", "/summary", "/crm", "/smm/"),
    "guest": ("/guest/",),
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
        await self.app(scope, receive, send)
