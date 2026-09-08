from fastapi import Request
from fastapi.responses import JSONResponse
from app.webapp.app import current_user


class UnifiedRBACMiddleware:
    """Backend guard for management APIs.

    Fine-grained permissions remain endpoint-level; this middleware prevents
    unauthenticated/unknown roles from entering the protected unified contour.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.startswith("/api/app/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        try:
            user, _ = await current_user(request)
            role = str(getattr(user, "role", "")).lower()
        except Exception:
            role = ""
        if role not in {"owner", "admin", "smm", "guest"}:
            response = JSONResponse({"detail": "Unified API role is not configured"}, status_code=403)
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["unified_role"] = role
        await self.app(scope, receive, send)
