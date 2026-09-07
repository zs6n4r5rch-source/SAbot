from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required, dec
from app.webapp.management_dashboard import _guest_groups, _guest_group_count, _index as management_index
from app.webapp.bar_finance import report as bar_report

MSK = ZoneInfo("Europe/Moscow")


def _wall_time(value):
    if value is None:
        return None
    return value.replace(tzinfo=MSK).isoformat()


def _rows(payload):
    value = payload.get("data") or payload.get("items") or payload.get("results") or []
    return value if isinstance(value, list) else []


async def _all_guest_sessions(date_from: str, date_to: str):
    rows = []
    page = 1
    while True:
        payload = await langame_client.guest_sessions(date_from, date_to, page=page, page_limit=500)
        page_rows = _rows(payload)
        if not page_rows:
            break
        rows.extend(r for r in page_rows if isinstance(r, dict))
        total_pages = payload.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


async def _all_session_revenue(date_from: str, date_to: str):
    rows = []
    page = 1
    while True:
        payload = await langame_client.all_operations_log(
            date_from, date_to, page=page, page_limit=500,
            operation_type="Списание", operation_form="Сессия",
        )
        page_rows = _rows(payload)
        if not page_rows:
            break
        rows.extend(r for r in page_rows if isinstance(r, dict))
        total_pages = payload.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    return rows


def _operation_amount(row):
    for key in ("amount", "balance_amount", "sum", "balance"):
        value = row.get(key)
        if value is not None:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                pass
    return 0.0


async def _live_langame(now):
    day = now.astimezone(MSK).date().isoformat()
    sessions = await _all_guest_sessions(day, day)
    active = [r for r in sessions if int(r.get("normal_stop", 1) or 0) == 0 and r.get("guest_id") is not None]
    active_guest_ids = {int(r["guest_id"]) for r in active}
    today_guest_ids = {int(r["guest_id"]) for r in sessions if r.get("guest_id") is not None}
    revenue_rows = await _all_session_revenue(day, day)
    gaming = sum(max(0.0, _operation_amount(r)) for r in revenue_rows if not r.get("cancel"))
    return {
        "active_guests": len(active_guest_ids),
        "active_sessions": len(active),
        "today_guests": len(today_guest_ids),
        "gaming_revenue": gaming,
        "source": "LANGAME /guests/sessions + /all_operations_log/list",
    }


async def _summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionLocal() as session:
        open_rows = (await session.execute(
            select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.ended_at.is_(None)).order_by(Shift.started_at)
        )).all()
        previous = (await session.execute(
            select(Shift, Employee, ShiftCloseReport)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id)
            .where(Shift.ended_at.is_not(None))
            .order_by(desc(Shift.ended_at)).limit(1)
        )).first()
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0
    try:
        live = await _live_langame(now)
    except LangameAPIError as exc:
        live = {"active_guests": None, "active_sessions": None, "today_guests": None, "gaming_revenue": None, "source": f"LANGAME unavailable: {exc}"}
    try:
        bar = await bar_report(start, now)
        bar_sales = float(bar.get("sales", 0) or 0)
    except LangameAPIError:
        bar_sales = 0.0
    groups = []
    try:
        for g in await _guest_groups():
            groups.append({**g, "count": await _guest_group_count(g["id"])})
    except LangameAPIError:
        pass
    prev = None
    if previous:
        shift, employee, report = previous
        prev = {"id": shift.id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "started_at": _wall_time(shift.started_at), "ended_at": _wall_time(shift.ended_at), "status": report.status if report else "no_report"}
    gaming = live["gaming_revenue"]
    total = None if gaming is None else bar_sales + gaming
    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "shifts": [{"id": s.id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": _wall_time(s.started_at)} for s, e in open_rows],
        "previous_report": prev,
        "sales": {"bar": bar_sales, "gaming": gaming, "total": total, "source": live["source"]},
        "guests": {"active": live["active_guests"], "today": live["today_guests"], "active_sessions": live["active_sessions"]},
        "groups": groups,
        "attention": {"critical_stock": int(critical), "dismissal_required": int(dismissals), "critical_total": int(critical) + int(dismissals)},
    }


JS = r'''<script>
function svMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function svEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function svTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
async function home(){if(me?.role!=='owner'){return legacyCurrentSummaryHome?.()};clear();setBottom(true);const d=await api('/api/current-summary-v2');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn" onclick="adminShiftOpen(${s.id})"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${svEsc(s.employee)}</span><span class="nav-hint">С ${svTime(s.started_at)}</span></span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${g.id})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${svEsc(g.name)}</span><span class="nav-hint">${g.count} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');const pr=d.previous_report;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${svTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="section-title"><h2>Выручка сегодня</h2></div><section class="card">${row('Бар и снеки',svMoney(d.sales.bar))}${row('Игровое время',svMoney(d.sales.gaming))}${row('Всего',svMoney(d.sales.total))}<div class="row-sub">${svEsc(d.sales.source)}</div></section><div class="section-title"><h2>Гости</h2><span>LANGAME</span></div><section class="card">${row('Гости сейчас · активная сессия',d.guests.active??'—')}${row('Активные сессии',d.guests.active_sessions??'—')}${row('Гости сегодня',d.guests.today??'—')}</section><div class="section-title"><h2>Гости и лояльность</h2><span>LANGAME</span></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Отчёт предыдущей смены</h2><span>1</span></div><div class="nav-card">${pr?`<button class="nav-btn" onclick="adminShiftOpen(${pr.id})"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">${svEsc(pr.employee)}</span><span class="nav-hint">${svTime(pr.started_at)} — ${svTime(pr.ended_at)} · ${svEsc(pr.status)}</span></span><span class="nav-arrow">›</span></button>`:'<div class="empty">Предыдущей смены нет</div>'}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${iconNav('📦','Критические остатки',String(d.attention.critical_stock),()=>inventory()).outerHTML}${iconNav('⚠️','Требуется решение',String(d.attention.dismissal_required),()=>attention()).outerHTML}</div>`}
async function adminShiftOpen(id){clear();setBottom(false);back();const d=await api('/api/admins');const a=(d.items||[]).find(x=>x.id===id);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">СМЕНА</div><div class="hero-title">${svEsc(a?.name||'Администратор')}</div><div class="hero-sub">Открытая смена.</div></section><button class="primary" onclick="admins()">Открыть администратора</button>`)}
</script>'''


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path in {"/api/current-summary-v2", "/"}:
            web_app.routes.remove(route)
    web_app.add_api_route("/api/current-summary-v2", _summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
