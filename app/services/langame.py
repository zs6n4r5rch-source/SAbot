from typing import Any
import httpx
from app.config import settings


class LangameAPIError(RuntimeError):
    pass


class LangameReadOnlyViolation(LangameAPIError):
    """Raised if code attempts to use a mutating LANGAME HTTP method."""


class LangameClient:
    def __init__(self):
        self.base_url = settings.langame_base_url.rstrip("/")
        if not settings.langame_read_only:
            raise LangameReadOnlyViolation("LANGAME write access is disabled by design; set LANGAME_READ_ONLY=true")
        self.headers = {"X-Request-Token": settings.langame_api_key}
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=httpx.Timeout(20.0, connect=10.0))

    async def aclose(self) -> None:
        await self.client.aclose()

    READ_ONLY_POST_PATHS = frozenset({"/guests/search"})
    MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        normalized_method = method.upper()
        normalized_path = path.split("?", 1)[0].rstrip("/") or "/"
        if normalized_method != "GET" and not (normalized_method == "POST" and normalized_path in self.READ_ONLY_POST_PATHS):
            raise LangameReadOnlyViolation(f"LANGAME is configured as read-only; blocked {normalized_method} {normalized_path}")
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise LangameAPIError(f"LANGAME network error: {exc}") from exc
        if response.status_code >= 400:
            raise LangameAPIError(f"LANGAME HTTP {response.status_code}: {response.text[:1000]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LangameAPIError("LANGAME returned invalid JSON") from exc
        if isinstance(data, dict) and data.get("status") is False:
            raise LangameAPIError(str(data))
        return data

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def _read_only_post(self, path: str, json: dict) -> dict:
        if path.rstrip("/") not in self.READ_ONLY_POST_PATHS:
            raise LangameReadOnlyViolation(f"POST endpoint is not allowlisted as read-only: {path}")
        return await self._request("POST", path, json=json)

    async def clubs(self) -> dict:
        return await self._get("/clubs/list")

    async def users(self, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/users/list", {"page": page, "page_limit": page_limit})

    async def shifts(self, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/working_shifts/list", {"page": page, "page_limit": page_limit})

    async def balances(self, date_from: str | None = None, date_to: str | None = None, page: int = 1, page_limit: int = 500) -> dict:
        params = {"page": page, "page_limit": page_limit}
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        return await self._get("/balances/list", params)

    async def guest_sessions(self, date_from: str | None = None, date_to: str | None = None, page: int = 1, page_limit: int = 500, guest_id: int | None = None) -> dict:
        params = {"page": page, "page_limit": page_limit}
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        if guest_id is not None: params["guest_id"] = guest_id
        return await self._get("/guests/sessions", params)

    async def active_guest_sessions(self, date_from: str | None = None, date_to: str | None = None, page: int = 1, page_limit: int = 500) -> dict:
        """Return only sessions currently active in LANGAME's dedicated active-session API."""
        params = {"page": page, "page_limit": page_limit}
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        return await self._get("/guests/sessions/active", params)

    async def transactions(self, date_from: str | None = None, date_to: str | None = None, page: int = 1, page_limit: int = 500, type: int | None = None, pay_system: int | None = None) -> dict:
        params = {"page": page, "page_limit": page_limit}
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        if type is not None: params["type"] = type
        if pay_system is not None: params["pay_system"] = pay_system
        return await self._get("/transactions/list", params)

    async def all_operations_log(self, date_from: str | None = None, date_to: str | None = None, page: int = 1, page_limit: int = 500, operation_type: str | None = None, operation_form: str | None = None) -> dict:
        params = {"page": page, "page_limit": page_limit}
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        if operation_type: params["operation_type"] = operation_type
        if operation_form: params["operation_form"] = operation_form
        return await self._get("/all_operations_log/list", params)

    async def products(self) -> dict:
        return await self._get("/products/list")

    async def stock(self, club_id: int, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/goods/list", {"club_id": club_id, "page": page, "page_limit": page_limit})

    async def product_sales(self, date_from: str, date_to: str, page: int = 1, page_limit: int = 100, sale_type: str | None = None) -> dict:
        params = {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": page_limit}
        if sale_type: params["type"] = sale_type
        return await self._get("/products/expense", params)

    async def product_arrivals(self, date_from: str, date_to: str, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/products/arrival", {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": page_limit})

    async def guest_groups(self) -> dict:
        return await self._get("/guests/groups")

    async def guests_search(self, query: str | None = None, phone: str | None = None, size: int = 20, page: int = 1, groups: list[int] | None = None) -> dict:
        filters: dict[str, Any] = {}
        if query: filters["query"] = query
        if phone: filters["phone"] = phone
        if groups: filters["groups"] = groups
        payload = {"pagination": {"page": page, "size": size}, "filter": filters, "featues": {"fields": ["guest_id", "phone", "fio", "simple_reg", "temp"]}}
        return await self._read_only_post("/guests/search", payload)

    async def guest_by_id(self, guest_id: int) -> dict:
        payload = {"filter": {"ids": [guest_id]}, "pagination": {"page": 1, "size": 1}, "featues": {"fields": ["guest_id", "fio", "phone", "simple_reg", "temp"], "balance": True, "bonus_balance": True, "black_list": True}}
        return await self._read_only_post("/guests/search", payload)


langame_client = LangameClient()
