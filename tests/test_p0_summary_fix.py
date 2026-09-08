import asyncio

from app.webapp import current_summary_v3
from app.webapp import p0_fixes


def test_p0_fix_counts_groups_from_pagination(monkeypatch):
    original = current_summary_v3._summary

    async def fake_summary(request):
        return {"groups": [{"id": 7, "name": "Gold", "count": None}]}

    class FakeClient:
        async def guests_search(self, **kwargs):
            assert kwargs == {"groups": [7], "size": 1, "page": 1}
            return {"pagination": {"total": 42}}

    monkeypatch.setattr(current_summary_v3, "_summary", fake_summary)
    monkeypatch.setattr("app.services.langame.langame_client", FakeClient())
    try:
        p0_fixes.apply()
        result = asyncio.run(current_summary_v3._summary(object()))
        assert result["groups"][0]["count"] == 42
    finally:
        current_summary_v3._summary = original
