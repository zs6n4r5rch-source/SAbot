from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.config import settings


def timezone_name() -> str:
    return getattr(settings, "report_timezone", None) or "Europe/Moscow"


def club_tz() -> ZoneInfo:
    return ZoneInfo(timezone_name())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return now_utc().astimezone(club_tz())


def local_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = (now or now_utc()).astimezone(club_tz())
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), local.astimezone(timezone.utc)
