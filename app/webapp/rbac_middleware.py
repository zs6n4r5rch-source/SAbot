from fastapi import Request
from fastapi.responses import JSONResponse
from app.webapp.app import current_user


class UnifiedRBACMiddleware:
    """Backend guard for the new management API.

    The frontend is never the authority for access. GUEST users cannot reach
    management data; SMM is intentionally restricted until its dedicated API
    contour is enabled.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/app/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        try:
            user, _ = await current_user(request)
            role = str(getattr(user, "role", "")).lower()
        except Exception:
            role = ""
        if role not in {"owner", "admin"}:
            response = JSONResponse({"detail": "Unified management API is restricted to OWNER/ADMIN"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
