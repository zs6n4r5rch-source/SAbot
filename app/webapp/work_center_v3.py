from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, Club, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required
from app.webapp.management_dashboard import _index as management_index
from app.webapp.bar_finance import report as bar_report

MSK = ZoneInfo("Europe/Moscow")


def _rows(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ("items", "data", "results", "rows"):
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []


async def _all_pages(method, *args, **kwargs):
    rows = []
    page = 1
    while page <= 50:
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = [x for x in _rows(payload) if isinstance(x, dict)]
        if not batch:
            break
        rows.extend(batch)
        pagination = payload.get("pagination") or {}
        total_pages = payload.get("total_pages") or pagination.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


def _money(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _wall(value):
    return value.replace(tzinfo=MSK).isoformat() if value else None


async def _work(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    day = start.date().isoformat()

    async with SessionLocal() as session:
        open_shifts = (await session.execute(
            select(Shift, Employee)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.ended_at.is_(None))
            .order_by(Shift.started_at)
        )).all()
        critical = (await session.execute(
            select(InventoryBalance, Product, Club)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Club, Club.id == InventoryBalance.club_id)
            .where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)
            .order_by(InventoryBalance.quantity)
        )).all()
        open_reports = (await session.execute(
            select(Shift, Employee, ShiftCloseReport)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id)
            .where(Shift.ended_at.is_(None))
        )).all()
        violations = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0

    sessions = []
    sessions_error = False
    try:
        sessions = await _all_pages(langame_client.guest_sessions, day, day)
    except LangameAPIError:
        sessions_error = True

    active = [s for s in sessions if int(s.get("normal_stop", 1) or 0) == 0 and s.get("guest_id") is not None]
    active_guests = len({int(s["guest_id"]) for s in active})

    try:
        bar = await bar_report(start, now)
    except LangameAPIError:
        bar = {"sales": None, "purchases": None, "profit": None, "products": []}

    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "hall": {
            "active_guests": None if sessions_error else active_guests,
            "active_sessions": None if sessions_error else len(active),
            "load": None,
            "bookings": None,
            "problem_pcs": None,
            "source": "LANGAME · Сессии",
        },
        "guests_now": [
            {
                "guest_id": int(s["guest_id"]),
                "session_id": s.get("id"),
                "started_at": s.get("date_start"),
                "ended_at": s.get("date_stop"),
                "pc": s.get("pc") or s.get("pc_name") or s.get("computer") or None,
            }
            for s in active
        ],
        "bar": {
            "sales": bar.get("sales"),
            "purchases": bar.get("purchases"),
            "profit": bar.get("profit"),
            "products": (bar.get("products") or [])[:10],
        },
        "shifts": [
            {
                "id": s.id,
                "employee": e.full_name if e else f"Администратор #{s.employee_id}",
                "started_at": _wall(s.started_at),
                "sales": _money(s.cash_sales) + _money(s.card_sales) + _money(s.mobile_sales),
                "cash": _money(s.cash_sales),
                "card": _money(s.card_sales),
                "online": _money(s.mobile_sales),
            }
            for s, e in open_shifts
        ],
        "warehouse": {
            "critical": len(critical),
            "items": [
                {"product": p.name, "club": c.name, "quantity": _money(b.quantity), "min_stock": _money(b.min_stock)}
                for b, p, c in critical
            ],
        },
        "control": {
            "open_without_report": sum(1 for _, _, r in open_reports if not r or r.status != "submitted"),
            "violations": int(violations),
            "critical_stock": len(critical),
        },
    }


JS = r'''<script>
function wcMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function wcEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]}))}
function wcTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
function wcRow(t,v){return `<div class="row"><div class="row-main"><div class="row-title">${wcEsc(t)}</div></div><div class="row-value">${wcEsc(v)}</div></div>`}
async function workCenter(){clear();setBottom(false);back();const d=await api('/api/work-center-v3');const guests=d.guests_now||[];root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель: что происходит и что требует действия сейчас.</div><div class="row-sub">Обновлено ${wcTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Зал</h2><span>LANGAME</span></div><section class="card">${wcRow('Гости сейчас',d.hall.active_guests??'—')}${wcRow('Активные сессии',d.hall.active_sessions??'—')}${wcRow('Загрузка',d.hall.load==null?'—':d.hall.load+'%')}${wcRow('Брони',d.hall.bookings??'—')}${wcRow('Проблемные ПК',d.hall.problem_pcs??'—')}<div class="row-sub">${wcEsc(d.hall.source)}</div></section><div class="section-title"><h2>Гости сейчас</h2><span>${guests.length}</span></div><div class="nav-card">${guests.map(g=>`<button class="nav-btn" onclick="crmGuestOpen(${g.guest_id})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">Гость #${g.guest_id}</span><span class="nav-hint">С ${wcTime(g.started_at)}${g.pc?' · '+wcEsc(g.pc):''}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Активных гостей сейчас нет</div>'}</div><div class="section-title"><h2>Бар и снеки</h2><span>сегодня</span></div><section class="card">${wcRow('Продажи',wcMoney(d.bar.sales))}${wcRow('Приходы / закупка',wcMoney(d.bar.purchases))}${wcRow('Прибыль',wcMoney(d.bar.profit))}<button class="primary" onclick="finance()">Открыть финансы</button></section><div class="section-title"><h2>Смены</h2><span>${d.shifts.length}</span></div><div class="nav-card">${d.shifts.map(s=>`<button class="nav-btn" onclick="admins()"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${wcEsc(s.employee)}</span><span class="nav-hint">С ${wcTime(s.started_at)} · наличные ${wcMoney(s.cash)} · карта ${wcMoney(s.card)} · онлайн ${wcMoney(s.online)}</span></span><span class="nav-arrow">${wcMoney(s.sales)}</span></button>`).join('')||'<div class="empty">Открытых смен нет</div>'}</div><div class="section-title"><h2>Склад</h2><span>${d.warehouse.critical}</span></div><div class="nav-card">${d.warehouse.items.map(x=>`<button class="nav-btn" onclick="inventory()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${wcEsc(x.product)}</span><span class="nav-hint">${wcEsc(x.club)} · ${x.quantity} / минимум ${x.min_stock}</span></span><span class="nav-arrow">⚠️</span></button>`).join('')||'<div class="empty">Критических остатков нет</div>'}</div><div class="section-title"><h2>Контроль</h2><span>${d.control.open_without_report+d.control.violations}</span></div><div class="nav-card">${wcRow('Смены без отчёта',d.control.open_without_report)}${wcRow('Критические остатки',d.control.critical_stock)}${wcRow('Требует решения',d.control.violations)}</div>`}
</script>'''


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path in ("/api/work-center-v2", "/api/work-center-v3"):
            web_app.routes.remove(route)
    web_app.add_api_route("/api/work-center-v3", _work, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
'''
