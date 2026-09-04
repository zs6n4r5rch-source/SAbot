from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.bot.analytics import sales_rows
from app.db.session import SessionLocal
from app.models import Employee, Shift


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _first(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _hours_from_row(row: dict) -> Decimal:
    value = _first(row, "hours", "hour", "duration_hours", "duration")
    if value is None:
        return Decimal("0")
    try:
        hours = Decimal(str(value))
        # A duration field reported in minutes is normalized when it is clearly > 24.
        return hours / Decimal("60") if hours > 24 else hours
    except Exception:
        return Decimal("0")


async def build_deep_stats(days: int = 30) -> dict:
    days = min(max(int(days), 1), 90)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    rows = await sales_rows(start, end)
    sales_total = Decimal("0")
    sold_units = Decimal("0")
    tariff_like: dict[str, dict] = {}
    purchased_hours = Decimal("0")

    for row in rows:
        if int(row.get("cancel", 0) or 0) == 1:
            continue
        qty = _decimal(row.get("count"))
        price = _decimal(row.get("price_sale"))
        sales_total += price * qty
        sold_units += qty

        # Keep tariff analysis conservative: only use explicit tariff/duration
        # fields if LANGAME actually returns them. Do not reinterpret a product
        # sale as a gaming tariff when the source does not identify it as one.
        tariff_name = _first(row, "tariff_name", "tariff", "package_name", "package", "name")
        tariff_type = _first(row, "tariff_type", "package_type", "type")
        duration = _hours_from_row(row)
        explicit_tariff = any(
            row.get(k) not in (None, "")
            for k in ("tariff_name", "tariff", "package_name", "package", "tariff_type", "package_type")
        )
        if explicit_tariff and tariff_name:
            key = str(tariff_name)
            item = tariff_like.setdefault(key, {"name": key, "type": tariff_type, "count": 0, "hours": 0.0, "revenue": 0.0})
            item["count"] += int(qty) if qty == qty.to_integral_value() else float(qty)
            item["hours"] += float(duration * qty)
            item["revenue"] += float(price * qty)
            purchased_hours += duration * qty

    async with SessionLocal() as session:
        shift_rows = (await session.execute(
            __import__("sqlalchemy").select(Shift, Employee)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.started_at >= start, Shift.started_at <= end)
        )).all()

    total_hours = Decimal("0")
    for shift, _employee in shift_rows:
        if shift.ended_at and shift.ended_at > shift.started_at:
            total_hours += Decimal(str((shift.ended_at - shift.started_at).total_seconds())) / Decimal("3600")

    # Retention requires guest registration + subsequent session/visit history.
    # The current read-only client does not expose that history, so returning
    # null is intentional rather than fabricating a percentage from guest count.
    return {
        "days": days,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "sales": float(sales_total),
        "units": float(sold_units),
        "average_unit_price": float(sales_total / sold_units) if sold_units else 0.0,
        "staff_hours": float(total_hours),
        "sales_per_staff_hour": float(sales_total / total_hours) if total_hours else 0.0,
        "tariffs": sorted(tariff_like.values(), key=lambda x: x["revenue"], reverse=True),
        "purchased_hours": float(purchased_hours) if purchased_hours else None,
        "retention": None,
        "retention_status": "недоступно через текущий read-only API клиента: нет истории регистраций и повторных сессий",
        "sources": {
            "sales": "LANGAME product_sales",
            "staff_hours": "локальные закрытые/открытые смены",
            "tariffs": "только если LANGAME явно возвращает tariff/package fields",
            "retention": "требуется LANGAME Rolling Retention / session history endpoint",
        },
    }
