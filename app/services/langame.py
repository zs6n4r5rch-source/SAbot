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
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=httpx.Timeout(20.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    # LANGAME is deliberately used as a read-only source of truth.
    # GET is the normal read path. The only POST allowed by the OpenAPI
    # contract is /guests/search, which is a search operation and does not
    # modify LANGAME data. Every other mutating HTTP method is blocked here.
    READ_ONLY_POST_PATHS = frozenset({"/guests/search"})
    MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        normalized_method = method.upper()
        normalized_path = path.split("?", 1)[0].rstrip("/") or "/"

        # Defense in depth: the client itself is the last gate before any
        # request reaches LANGAME. Only GET and the explicitly allowlisted
        # non-mutating search endpoint are permitted. Future code cannot
        # accidentally add a PUT/PATCH/DELETE (or an arbitrary POST).
        if normalized_method == "GET":
            pass
        elif normalized_method == "POST" and normalized_path in self.READ_ONLY_POST_PATHS:
            pass
        else:
            raise LangameReadOnlyViolation(
                f"LANGAME is configured as read-only; blocked {normalized_method} {normalized_path}"
            )
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise LangameAPIError(f"LANGAME network error: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:1000]
            raise LangameAPIError(f"LANGAME HTTP {response.status_code}: {detail}")
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
        """POST endpoint explicitly classified as read-only by LANGAME API."""
        if path.rstrip("/") not in self.READ_ONLY_POST_PATHS:
            raise LangameReadOnlyViolation(f"POST endpoint is not allowlisted as read-only: {path}")
        return await self._request("POST", path, json=json)

    async def clubs(self) -> dict:
        return await self._get("/clubs/list")

    async def users(self, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/users/list", {"page": page, "page_limit": page_limit})

    async def shifts(self, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/working_shifts/list", {"page": page, "page_limit": page_limit})

    async def products(self) -> dict:
        return await self._get("/products/list")

    async def stock(self, club_id: int, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/goods/list", {"club_id": club_id})

    async def product_sales(self, date_from: str, date_to: str, page: int = 1, page_limit: int = 100, sale_type: str | None = None) -> dict:
        params = {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": page_limit}
        if sale_type:
            params["type"] = sale_type
        return await self._get("/products/expense", params)

    async def product_arrivals(self, date_from: str, date_to: str, page: int = 1, page_limit: int = 100) -> dict:
        return await self._get("/products/arrival", {"date_from": date_from, "date_to": date_to, "page": page, "page_limit": page_limit})

    async def guest_groups(self) -> dict:
        return await self._get("/guests/groups")

    async def guests_search(self, query: str | None = None, phone: str | None = None, size: int = 20, page: int = 1, groups: list[int] | None = None) -> dict:
        filters: dict[str, Any] = {}
        if query:
            filters["query"] = query
        if phone:
            filters["phone"] = phone
        if groups:
            filters["groups"] = groups
        payload = {
            "pagination": {"page": page, "size": size},
            "filter": filters,
            "featues": {"fields": ["guest_id", "phone", "fio", "simple_reg", "temp"]},
        }
        return await self._read_only_post("/guests/search", payload)

    async def guest_by_id(self, guest_id: int) -> dict:
        payload = {
            "filter": {"ids": [guest_id]},
            "pagination": {"page": 1, "size": 1},
            "featues": {"fields": ["guest_id", "fio", "phone", "simple_reg", "temp"], "balance": True, "bonus_balance": True, "black_list": True},
        }
        return await self._read_only_post("/guests/search", payload)


# One shared HTTP client per bot process. Feature modules alias this client so
# we do not leak one AsyncClient per router.
langame_client = LangameClient()
