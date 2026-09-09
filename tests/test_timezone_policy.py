from datetime import datetime, timezone

from app.services.timezone_policy import local_day_bounds, local_period_bounds


def test_local_day_bounds_uses_configured_club_timezone(monkeypatch):
    monkeypatch.setattr("app.services.timezone_policy.settings.report_timezone", "Europe/Moscow")
    start, end = local_day_bounds(datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-09-08T21:00:00+00:00"
    assert end.isoformat() == "2026-09-09T15:30:00+00:00"


def test_local_day_bounds_handles_dst(monkeypatch):
    monkeypatch.setattr("app.services.timezone_policy.settings.report_timezone", "Europe/Amsterdam")
    start, end = local_day_bounds(datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-10-24T22:00:00+00:00"
    assert end.isoformat() == "2026-10-25T12:00:00+00:00"


def test_local_period_bounds_preserves_local_clock_across_dst(monkeypatch):
    monkeypatch.setattr("app.services.timezone_policy.settings.report_timezone", "Europe/Amsterdam")
    start, end = local_period_bounds(2, datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-10-24T11:00:00+00:00"
    assert end.isoformat() == "2026-10-26T12:00:00+00:00"
