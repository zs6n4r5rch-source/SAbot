"""Small compatibility fixes applied before web feature routes are registered.

Keep these patches narrow: feature modules remain the owners of their APIs,
while this module only repairs known data-shape/runtime defects without taking
ownership of the root page.
"""

from functools import wraps


def apply() -> None:
    from app.webapp import current_summary_v3

    original = current_summary_v3._summary
    if getattr(original, "_p0_fixed", False):
        return

    @wraps(original)
    async def fixed_summary(request):
        data = await original(request)
        groups = data.get("groups") or []
        if groups:
            from app.services.langame import LangameAPIError, langame_client
            for group in groups:
                try:
                    payload = await langame_client.guests_search(
                        groups=[int(group["id"])], size=1, page=1
                    )
                    pagination = payload.get("pagination") or {}
                    total = payload.get("total", pagination.get("total", 0))
                    group["count"] = int(total or 0)
                except (LangameAPIError, TypeError, ValueError, KeyError):
                    # Preserve the existing value when LANGAME cannot answer.
                    pass
        return data

    fixed_summary._p0_fixed = True
    current_summary_v3._summary = fixed_summary
