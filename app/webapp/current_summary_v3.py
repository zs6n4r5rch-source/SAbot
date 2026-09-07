from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
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
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _rows(value)
            if nested:
                return nested
    return []


def _wall_time(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).isoformat()


async def _all_pages(method, *args, **kwargs):
    rows, page = [], 1
    while page <= 50:
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = [r for r in _rows(payload) if isinstance(r, dict)]
        if not batch:
            break
        rows.extend(batch)
        if isinstance(payload, dict):
            p = payload.get("pagination") or {}
            last = payload.get("total_pages") or p.get("total_pages") or p.get("last_page")
            if last and page >= int(last):
                break
        page += 1
    return rows


def _money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _active(row):
    try:
        return int(row.get("normal_stop", 1) or 0) == 0
    except (TypeError, ValueError):
        return str(row.get("normal_stop")).lower() in {"false", "0", "no"}


async def _live_langame(now):
    local = now.astimezone(MSK)
    today = local.date()
    sessions = await _all_pages(langame_client.guest_sessions, (today - timedelta(days=1)).isoformat(), today.isoformat())
    active = [r for r in sessions if _active(r) and r.get("guest_id") is not None]
    today_sessions = [r for r in sessions if r.get("guest_id") is not None and str(r.get("date_start", ""))[:10] == today.isoformat()]
    balances = await _all_pages(langame_client.balances, today.isoformat(), today.isoformat())
    products = await _all_pages(langame_client.product_sales, today.isoformat(), today.isoformat())
    gaming = sum(max(0.0, _money(r.get("amount"))) for r in balances)
    bar = sum(max(0.0, _money(r.get("price_sale")) * _money(r.get("count"))) for r in products if not int(r.get("cancel", 0) or 0))
    return {"active": len({int(r["guest_id"]) for r in active}), "active_sessions": len(active), "today": len({int(r["guest_id"]) for r in today_sessions}), "gaming": gaming, "bar": bar}


async def _guest_groups():
    return [{"id": int(r["id"]), "name": str(r["name"])} for r in _rows(await langame_client.guest_groups()) if isinstance(r, dict) and r.get("id") is not None and r.get("name")]


async def _group_count(group_id):
    payload = await langame_client.guests_search(groups=[int(group_id)], size=1, page=1)
    return int((payload.get("pagination") or {}).get("total", 0) or 0)


async def _group_guests(group_id):
    rows, page = [], 1
    while page <= 50:
        payload = await langame_client.guests_search(groups=[int(group_id)], size=100, page=page)
        batch = [r for r in _rows(payload) if isinstance(r, dict)]
        if not batch:
            break
        rows.extend(batch)
        last = (payload.get("pagination") or {}).get("last_page")
        if last and page >= int(last):
            break
        page += 1
    return rows


async def _guest_api(request: Request, guest_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    try:
        rows = _rows(await langame_client.guest_by_id(int(guest_id)))
        guest = rows[0] if rows else {}
        return {"guest_id": int(guest_id), "fio": guest.get("fio") or guest.get("name") or guest.get("phone") or f"Гость #{guest_id}", "phone": guest.get("phone") or "", "balance": guest.get("balance"), "bonus_balance": guest.get("bonus_balance"), "black_list": guest.get("black_list")}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest unavailable: {exc}") from exc


async def _group_guests_api(request: Request, group_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    try:
        rows = await _group_guests(group_id)
        return {"group_id": int(group_id), "items": [{"guest_id": r.get("guest_id", r.get("id")), "fio": r.get("fio") or r.get("name") or r.get("phone") or "Без имени", "phone": r.get("phone") or ""} for r in rows if r.get("guest_id", r.get("id")) is not None]}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc


async def _summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    day = now.astimezone(MSK).date().isoformat()
    async with SessionLocal() as session:
        open_rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        previous = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0
    try:
        live = await _live_langame(now)
    except LangameAPIError:
        live = {"active": None, "active_sessions": None, "today": None, "gaming": None, "bar": None}
    groups = []
    try:
        for group in await _guest_groups():
            try:
                count = await _group_count(group["id"])
            except LangameAPIError:
                count = None
            groups.append({**group, "count": count})
    except LangameAPIError:
        pass
    prev = None
    if previous:
        shift, employee, report = previous
        prev = {"id": shift.id, "report_id": report.id if report else None, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "started_at": _wall_time(shift.started_at), "ended_at": _wall_time(shift.ended_at), "status": report.status if report else "no_report"}
    total = None if live["gaming"] is None or live["bar"] is None else live["gaming"] + live["bar"]
    return {"updated_at": now.astimezone(MSK).isoformat(), "day": day, "shifts": [{"id": s.id, "employee_id": s.employee_id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": _wall_time(s.started_at)} for s, e in open_rows], "previous_report": prev, "sales": {"bar": live["bar"], "gaming": live["gaming"], "total": total}, "guests": {"active": live["active"], "today": live["today"], "active_sessions": live["active_sessions"]}, "groups": groups, "attention": {"critical_stock": int(critical), "dismissal_required": int(dismissals), "critical_total": int(critical) + int(dismissals)}}


JS = r"""<script>
const svLegacyHome=window.home;
function svMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function svEsc(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
function svTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
function svRow(t,v){return `<div class="row"><div class="row-main"><div class="row-title">${svEsc(t)}</div></div><div class="row-value">${svEsc(v)}</div></div>`}
function svBack(){root.prepend(btn('← Назад',window.home,'back'))}
async function crmGroup(id){clear();setBottom(false);const d=await api('/api/current-summary-v2/guests?group_id='+id);const g=(window.__summaryGroups||[]).find(x=>String(x.id)===String(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ГОСТИ · ГРУППА</div><div class="hero-title">${svEsc(g?.name||'Группа')}</div></section><div class="nav-card">${(d.items||[]).map(x=>`<button class="nav-btn" onclick="crmGuestOpen(${Number(x.guest_id)})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">${svEsc(x.fio)}</span><span class="nav-hint">${svEsc(x.phone)}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Гости не найдены</div>'}</div>`;svBack()}
async function crmGuestOpen(id){clear();setBottom(false);const d=await api('/api/current-summary-v2/guest/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ГОСТЬ</div><div class="hero-title">${svEsc(d.fio)}</div><div class="hero-sub">LANGAME #${Number(d.guest_id)}</div></section><section class="card">${svRow('Телефон',d.phone||'—')}${svRow('Баланс',svMoney(d.balance))}${svRow('Бонусы',svMoney(d.bonus_balance))}${svRow('Статус',d.black_list?'Чёрный список':'Обычный')}</section>`;svBack()}
async function svReport(id){if(!id)return;clear();setBottom(false);const d=await api('/api/work-center-v3/reports/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ОТЧЁТ О СМЕНЕ</div><div class="hero-title">${svEsc(d.employee)}</div><div class="hero-sub">${svTime(d.started_at)} — ${svTime(d.ended_at)}</div></section><section class="card">${svRow('Статус',d.status)}${svRow('Расчётная наличность',svMoney(d.cash_expected))}${svRow('Фактическая наличность',svMoney(d.cash_actual))}${svRow('Разница кассы',d.cash_difference==null?'—':svMoney(d.cash_difference))}${svRow('Проверено товаров',d.stock_items_count??'—')}${svRow('Расхождений',d.stock_discrepancies_count??0)}</section>`;svBack()}
async function svAttention(){if(typeof window.workControl==='function')return window.workControl();clear();setBottom(false);root.innerHTML='<div class="empty">Контроль доступен из меню «Работа».</div>';svBack()}
window.home=async function(){if(me?.role!=='owner')return svLegacyHome?.();clear();setBottom(true);const d=await api('/api/current-summary-v2');window.__summaryGroups=d.groups||[];document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn" onclick="summaryAdminOpen(${Number(s.employee_id)})"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${svEsc(s.employee)}</span><span class="nav-hint">С ${svTime(s.started_at)}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${Number(g.id)})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${svEsc(g.name)}</span><span class="nav-hint">${g.count===null?'нет данных':g.count+' гостей'}</span></span><span class="nav-arrow">›</span></button>`).join('');const pr=d.previous_report;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${svTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="section-title"><h2>Выручка сегодня</h2></div><section class="card">${svRow('Бар и снеки',svMoney(d.sales.bar))}${svRow('Игровое время',svMoney(d.sales.gaming))}${svRow('Всего',svMoney(d.sales.total))}</section><div class="section-title"><h2>Гости</h2><span>LANGAME</span></div><section class="card">${svRow('Гости сейчас',d.guests.active??'—')}${svRow('Гости сегодня',d.guests.today??'—')}</section><div class="section-title"><h2>Гости и лояльность</h2><span>LANGAME</span></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Отчёт предыдущей смены</h2><span>1</span></div><div class="nav-card">${pr?`<button class="nav-btn" onclick="svReport(${Number(pr.report_id||0)})"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">${svEsc(pr.employee)}</span><span class="nav-hint">${svTime(pr.started_at)} — ${svTime(pr.ended_at)} · ${svEsc(pr.status)}</span></span><span class="nav-arrow">›</span></button>`:'<div class="empty">Предыдущей смены нет</div>'}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${d.attention.critical_stock?`<button class="nav-btn" onclick="window.workWarehouse?workWarehouse():svAttention()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${d.attention.critical_stock} позиций</span></span><span class="nav-arrow">›</span></button>`:''}${d.attention.dismissal_required?`<button class="nav-btn" onclick="svAttention()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Требуется решение</span><span class="nav-hint">${d.attention.dismissal_required}</span></span><span class="nav-arrow">›</span></button>`:''}${!d.attention.critical_total?'<div class="empty">Критических вопросов нет</div>':''}</div>`}
</script>"""


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path in ("/api/current-summary-v2", "/api/current-summary-v2/guests", "/api/current-summary-v2/guest/{guest_id}"):
            web_app.routes.remove(route)
    web_app.add_api_route("/api/current-summary-v2", _summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/current-summary-v2/guests", _group_guests_api, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/current-summary-v2/guest/{guest_id}", _guest_api, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
'''
# fix compile
compile(current_py, "<current>