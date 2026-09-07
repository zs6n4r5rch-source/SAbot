from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required
from app.webapp.management_dashboard import _index as management_index

MSK = ZoneInfo("Europe/Moscow")


def _rows(payload):
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ("items", "data", "results", "rows"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return []


def _wall_time(value):
    return value.replace(tzinfo=MSK).isoformat() if value else None


async def _all_pages(method, *args, **kwargs):
    rows = []
    page = 1
    while page <= 50:
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = [r for r in _rows(payload) if isinstance(r, dict)]
        if not batch:
            break
        rows.extend(batch)
        total_pages = payload.get("total_pages") or (payload.get("pagination") or {}).get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def _all_guest_sessions(date_from, date_to):
    return await _all_pages(langame_client.guest_sessions, date_from, date_to)


async def _all_balances(date_from, date_to):
    return await _all_pages(langame_client.balances, date_from, date_to)


async def _all_product_sales(date_from, date_to):
    return await _all_pages(langame_client.product_sales, date_from, date_to)


def _money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _balance_amount(row):
    return _money(row.get("amount"))


def _product_sale_amount(row):
    qty = _money(row.get("count", row.get("quantity", 0)))
    if row.get("price_sale") is not None:
        return _money(row.get("price_sale")) * qty
    for key in ("sum", "amount", "total", "revenue"):
        if row.get(key) is not None:
            return _money(row.get(key))
    return 0.0


async def _live_langame(now):
    day = now.astimezone(MSK).date().isoformat()
    sessions = await _all_guest_sessions(day, day)
    active = [r for r in sessions if int(r.get("normal_stop", 1) or 0) == 0 and r.get("guest_id") is not None]
    active_guest_ids = {int(r["guest_id"]) for r in active}
    today_guest_ids = {int(r["guest_id"]) for r in sessions if r.get("guest_id") is not None}
    balances = await _all_balances(day, day)
    products = await _all_product_sales(day, day)
    gaming = sum(max(0.0, _balance_amount(r)) for r in balances)
    food_services = sum(max(0.0, _product_sale_amount(r)) for r in products if not int(r.get("cancel", 0) or 0))
    return {
        "active_guests": len(active_guest_ids),
        "active_sessions": len(active),
        "today_guests": len(today_guest_ids),
        "gaming_revenue": gaming,
        "bar_revenue": food_services,
    }


async def _guest_groups():
    payload = await langame_client.guest_groups()
    groups = []
    for g in _rows(payload):
        if not isinstance(g, dict):
            continue
        gid = g.get("id", g.get("group_id"))
        if gid is None:
            continue
        groups.append({"id": int(gid), "name": str(g.get("name") or g.get("title") or f"Группа #{gid}")})
    return groups


async def _group_count(gid):
    payload = await langame_client.guests_search(groups=[int(gid)], size=1, page=1)
    pagination = payload.get("pagination") or {}
    for source in (pagination, payload):
        for key in ("total", "total_count", "count"):
            if source.get(key) is not None:
                return int(source[key] or 0)
    return len(_rows(payload))


async def _summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    day = start.date().isoformat()

    async with SessionLocal() as session:
        open_rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        previous = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0

    try:
        live = await _live_langame(now)
    except LangameAPIError:
        live = {"active_guests": None, "active_sessions": None, "today_guests": None, "gaming_revenue": None, "bar_revenue": None}

    groups = []
    try:
        for group in await _guest_groups():
            try:
                count = await _group_count(group["id"])
            except LangameAPIError:
                count = None
            groups.append({**group, "count": count})
    except LangameAPIError:
        groups = []

    prev = None
    if previous:
        shift, employee, report = previous
        prev = {"id": shift.id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "started_at": _wall_time(shift.started_at), "ended_at": _wall_time(shift.ended_at), "status": report.status if report else "no_report"}

    gaming = live["gaming_revenue"]
    bar = live["bar_revenue"]
    total = None if gaming is None or bar is None else gaming + bar
    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "day": day,
        "shifts": [{"id": s.id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": _wall_time(s.started_at)} for s, e in open_rows],
        "previous_report": prev,
        "sales": {"bar": bar, "gaming": gaming, "total": total},
        "guests": {"active": live["active_guests"], "today": live["today_guests"], "active_sessions": live["active_sessions"]},
        "groups": groups,
        "attention": {"critical_stock": int(critical), "dismissal_required": int(dismissals), "critical_total": int(critical) + int(dismissals)},
    }


JS = r'''<script>
function svMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function svEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function svTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
function svRow(title,value){return `<div class="row"><div class="row-main"><div class="row-title">${svEsc(title)}</div></div><div class="row-value">${svEsc(value)}</div></div>`}
async function crmGroup(id){clear();setBottom(false);back();const d=await api('/api/crm/guests?group_id='+encodeURIComponent(id));const payload=d.data||{};const items=payload.data||payload.items||payload.results||[];const group=(window.__summaryGroups||[]).find(g=>String(g.id)===String(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ГОСТИ · ГРУППА</div><div class="hero-title">${svEsc(group?.name||'Группа')}</div><div class="hero-sub">Гости выбранной группы LANGAME.</div></section><div class="section-title"><h2>Гости</h2><span>${items.length}</span></div><div class="nav-card">${items.map(g=>`<button class="nav-btn" onclick="crmGuestOpen(${g.guest_id||g.id||0})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">${svEsc(g.fio||g.name||'Без имени')}</span><span class="nav-hint">${svEsc(g.phone||'')}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">В этой группе гости не найдены</div>'}</div>`}
async function crmGuestOpen(id){if(typeof crmGuest==='function'){return crmGuest(id)}if(typeof clientOpen==='function'){return clientOpen(id)}window.location.hash='guest-'+id}
async function home(){if(me?.role!=='owner'){return legacyCurrentSummaryHome?.()};clear();setBottom(true);const d=await api('/api/current-summary-v2');window.__summaryGroups=d.groups||[];document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn" onclick="adminShiftOpen(${s.id})"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${svEsc(s.employee)}</span><span class="nav-hint">С ${svTime(s.started_at)}</span></span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${g.id})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${svEsc(g.name)}</span><span class="nav-hint">${g.count===null?'нет данных':g.count+' гостей'}</span></span><span class="nav-arrow">›</span></button>`).join('');const pr=d.previous_report;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${svTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="section-title"><h2>Выручка сегодня</h2></div><section class="card">${svRow('Бар и снеки',svMoney(d.sales.bar))}${svRow('Игровое время',svMoney(d.sales.gaming))}${svRow('Всего',svMoney(d.sales.total))}</section><div class="section-title"><h2>Гости</h2><span>LANGAME</span></div><section class="card">${svRow('Гости сейчас · активная сессия',d.guests.active??'—')}${svRow('Активные сессии',d.guests.active_sessions??'—')}${svRow('Гости сегодня',d.guests.today??'—')}</section><div class="section-title"><h2>Гости и лояльность</h2><span>LANGAME</span></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Отчёт предыдущей смены</h2><span>1</span></div><div class="nav-card">${pr?`<button class="nav-btn" onclick="adminShiftOpen(${pr.id})"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">${svEsc(pr.employee)}</span><span class="nav-hint">${svTime(pr.started_at)} — ${svTime(pr.ended_at)} · ${svEsc(pr.status)}</span></span><span class="nav-arrow">›</span></button>`:'<div class="empty">Предыдущей смены нет</div>'}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${iconNav('📦','Критические остатки',String(d.attention.critical_stock),()=>inventory()).outerHTML}${iconNav('⚠️','Требуется решение',String(d.attention.dismissal_required),()=>attention()).outerHTML}</div>`}
async function adminShiftOpen(id){clear();setBottom(false);back();const d=await api('/api/admins');const a=(d.items||[]).find(x=>x.id===id);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">СМЕНА</div><div class="hero-title">${svEsc(a?.name||'Администратор')}</div><div class="hero-sub">Открытая смена.</div></section><button class="primary" onclick="admins()">Открыть администратора</button>`)}
</script>'''


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/api/current-summary-v2":
            web_app.routes.remove(route)
    web_app.add_api_route("/api/current-summary-v2", _summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
