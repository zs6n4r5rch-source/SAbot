from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select, desc

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, Club, SalaryPeriod, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required, dec
from app.webapp.current_summary import _index as current_summary_index

MSK = ZoneInfo("Europe/Moscow")


def _rows(payload):
    return payload.get("data") or payload.get("items") or []


def _product_map(products):
    out = {}
    for p in _rows(products):
        try:
            pid = int(p.get("id", p.get("product_id", p.get("langame_product_id"))))
        except (TypeError, ValueError):
            continue
        out[pid] = (str(p.get("name") or ""), str(p.get("category_name") or p.get("category") or ""))
    return out


def _sale_kind(row, product_map):
    try:
        pid = int(row.get("product_id", row.get("productId", row.get("id"))))
    except (TypeError, ValueError):
        pid = None
    name = str(row.get("product_name") or row.get("productName") or row.get("name") or "")
    category = ""
    if pid in product_map:
        name += " " + product_map[pid][0]
        category = product_map[pid][1]
    text = f"{name} {category}".lower()
    bar_words = ("бар", "снек", "напит", "еда", "кофе", "чай", "пицц", "бургер", "food", "drink", "snack")
    return "bar" if any(x in text for x in bar_words) else "gaming"


async def _sales(start, end):
    products = await langame_client.products()
    pmap = _product_map(products)
    rows = []
    page = 1
    while page <= 50:
        result = await langame_client.product_sales(start.astimezone(MSK).date().isoformat(), end.astimezone(MSK).date().isoformat(), page=page, page_limit=100)
        batch = _rows(result)
        if not batch:
            break
        rows.extend(batch)
        total_pages = result.get("total_pages")
        if not total_pages or page >= int(total_pages):
            break
        page += 1
    totals = {"bar": 0.0, "gaming": 0.0, "units": 0.0}
    by_day = {}
    by_guest = {}
    for r in rows:
        if int(r.get("cancel", 0) or 0) == 1:
            continue
        try:
            qty = float(r.get("count", r.get("quantity", 0)) or 0)
            price = float(r.get("price_sale", r.get("price", 0)) or 0)
        except (TypeError, ValueError):
            continue
        amount = qty * price
        kind = _sale_kind(r, pmap)
        totals[kind] += amount
        totals["units"] += qty
        raw_date = str(r.get("date") or r.get("created_at") or r.get("createdAt") or start.astimezone(MSK).date().isoformat())[:10]
        d = by_day.setdefault(raw_date, {"bar": 0.0, "gaming": 0.0, "total": 0.0, "units": 0.0})
        d[kind] += amount
        d["total"] += amount
        d["units"] += qty
        gid = r.get("guest_id", r.get("guestId"))
        if gid is not None:
            g = by_guest.setdefault(str(gid), {"guest_id": gid, "spent": 0.0, "bar": 0.0, "gaming": 0.0, "units": 0.0})
            g["spent"] += amount
            g[kind] += amount
            g["units"] += qty
    return {"bar": totals["bar"], "gaming": totals["gaming"], "total": totals["bar"] + totals["gaming"], "units": totals["units"], "by_day": by_day, "by_guest": list(by_guest.values()), "rows": rows}


async def _guest_groups():
    data = await langame_client.guest_groups()
    result = []
    for g in _rows(data):
        gid = g.get("id", g.get("group_id"))
        if gid is None:
            continue
        result.append({"id": int(gid), "name": str(g.get("name") or g.get("title") or f"Группа #{gid}")})
    return result


async def _guest_group_count(gid):
    data = await langame_client.guests_search(groups=[int(gid)], size=1, page=1)
    pagination = data.get("pagination") or {}
    for key in ("total", "total_count", "count"):
        if key in data:
            return int(data[key] or 0)
        if key in pagination:
            return int(pagination[key] or 0)
    return len(_rows(data))


async def _crm_overview(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 3650)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    groups = await _guest_groups()
    counts = []
    for g in groups:
        try:
            count = await _guest_group_count(g["id"])
        except LangameAPIError:
            count = 0
        counts.append({**g, "count": count})
    try:
        guests_today = await langame_client.guests_search(size=100, page=1)
        today_count = len(_rows(guests_today))
    except LangameAPIError:
        today_count = 0
    sales = await _sales(start, end)
    try:
        guests_all = await langame_client.guests_search(size=100, page=1)
        total = (guests_all.get("pagination") or {}).get("total") or guests_all.get("total") or len(_rows(guests_all))
    except LangameAPIError:
        total = 0
    return {"period_days": days, "total_guests": int(total), "today_guests": int(today_count), "active_guests": None, "active_source": "LANGAME: endpoint not exposed by current read-only client", "groups": counts, "sales": {"total": sales["total"], "bar": sales["bar"], "gaming": sales["gaming"]}, "guest_spend": sales["by_guest"], "limits": {"guest_search_page_size": 100}}


async def _crm_guests(request: Request, group_id: int | None = None, q: str = "", page: int = 1):
    user, _ = await current_user(request)
    owner_required(user)
    groups = [group_id] if group_id else None
    data = await langame_client.guests_search(query=q or None, groups=groups, size=50, page=max(1, page))
    return {"source": "langame", "data": data}


async def _analytics_plus(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 3650)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    sales = await _sales(start, end)
    async with SessionLocal() as session:
        shifts = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start))).all()
    return {"days": days, "from": start.isoformat(), "to": end.isoformat(), "revenue": {"total": sales["total"], "bar": sales["bar"], "gaming": sales["gaming"]}, "units": sales["units"], "guests": {"today": None, "active": None, "note": "Активные гости требуют отдельного подтверждённого LANGAME read-only источника."}, "sessions": {"count": None, "hours": None}, "shifts": [{"employee": e.full_name if e else f"#{s.employee_id}", "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None} for s, e in shifts], "daily": [{"date": k, **v} for k, v in sorted(sales["by_day"].items())]}


async def _finance_plus(request: Request, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 3650)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    sales = await _sales(start, end)
    from app.webapp.bar_finance import report as bar_report
    bar = await bar_report(start, end)
    async with SessionLocal() as session:
        salary = await session.scalar(select(func.coalesce(func.sum(SalaryPeriod.total_amount), 0)).where(SalaryPeriod.date_from >= start.date(), SalaryPeriod.date_to <= end.date())) or 0
        penalties = await session.scalar(select(func.coalesce(func.sum(SalaryViolation.amount), 0)).where(SalaryViolation.created_at >= start, SalaryViolation.created_at <= end)) or 0
        shifts = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start).order_by(desc(Shift.started_at)))).all()
    purchase = float(bar.get("purchases", bar.get("arrival_cost", 0)) or 0)
    return {"days": days, "revenue": {"total": sales["total"], "gaming": sales["gaming"], "bar": sales["bar"]}, "bar": bar, "expenses": {"bar_purchases": purchase, "salary": dec(salary), "penalties": dec(penalties), "total": purchase + dec(salary) + dec(penalties)}, "profit": sales["total"] - purchase - dec(salary) - dec(penalties), "shifts": [{"id": s.id, "employee": e.full_name if e else f"#{s.employee_id}", "cash": dec(s.cash_sales), "card": dec(s.card_sales), "online": dec(s.mobile_sales), "ended": bool(s.ended_at)} for s, e in shifts]}


async def _work_center(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        open_rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        critical = (await session.execute(select(InventoryBalance, Product, Club).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock).order_by(InventoryBalance.quantity))).all()
        reports = (await session.execute(select(ShiftCloseReport, Shift, Employee).join(Shift, Shift.id == ShiftCloseReport.shift_id).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)))).all()
    return {"updated_at": now.astimezone(MSK).isoformat(), "shifts": [{"id": s.id, "employee": e.full_name if e else f"#{s.employee_id}", "started_at": s.started_at.astimezone(MSK).isoformat(), "sales": dec(s.cash_sales) + dec(s.card_sales) + dec(s.mobile_sales)} for s, e in open_rows], "critical_stock": [{"product": p.name, "club": c.name, "quantity": dec(b.quantity), "min_stock": dec(b.min_stock)} for b, p, c in critical], "open_without_report": [{"id": s.id, "employee": e.full_name if e else f"#{s.employee_id}"} for r, s, e in reports if r.status != "submitted"], "hall": {"active_guests": None, "sessions": None, "load": None, "source": "LANGAME active-session source not exposed by current read-only client"}}


JS = r'''<script>
const mgMoney=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const mgEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mgPeriod=(fn)=>`<div class="nav-card" style="display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px">${[1,7,30,90,365].map(d=>`<button class="secondary" style="width:auto;padding:9px 12px" onclick="${fn}(${d})">${d===1?'Сегодня':d+' дн.'}</button>`).join('')}</div>`;
async function clients(days=30){clear();setBottom(false);back();const d=await api('/api/crm/overview?days='+days);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">CRM</div><div class="hero-title">Клиенты</div><div class="hero-sub">Данные гостей и групп лояльности из LANGAME.</div></section>${mgPeriod('clients')}<div class="kpis"><div class="kpi"><div class="kpi-label">Всего гостей</div><div class="kpi-value">${d.total_guests}</div></div><div class="kpi"><div class="kpi-label">Были сегодня</div><div class="kpi-value">${d.today_guests}</div></div><div class="kpi"><div class="kpi-label">Сейчас</div><div class="kpi-value warn">${d.active_guests??'—'}</div></div><div class="kpi"><div class="kpi-label">Расходы за период</div><div class="kpi-value">${mgMoney(d.sales.total)}</div></div></div><div class="section-title"><h2>Лояльность</h2><span>LANGAME</span></div><div class="nav-card">${(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${g.id})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${mgEsc(g.name)}</span><span class="nav-hint">${g.count} гостей</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Покупки и расходы</h2><span>${days} дней</span></div><section class="card">${row('Бар и снеки',mgMoney(d.sales.bar))}${row('Игровое время',mgMoney(d.sales.gaming))}${row('Всего',mgMoney(d.sales.total))}</section><button class="primary" onclick="crmSearch()">Открыть список гостей</button><div class="card muted">Сессии, часы и детальная история покупок показываются только там, где LANGAME API отдаёт соответствующие поля.</div>`)}
async function crmSearch(groupId=null){clear();setBottom(false);back();const q=prompt('Поиск гостя (ФИО/телефон), можно оставить пустым')??'';const d=await api('/api/crm/guests?'+(groupId?`group_id=${groupId}&`:'')+'q='+encodeURIComponent(q));const items=d.data?.data||d.data?.items||[];root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Гости</h2><span>${items.length}</span></div>${items.map(g=>`<section class="card"><div class="admin-name">${mgEsc(g.fio||g.name||'Без имени')}</div><div class="admin-meta">${mgEsc(g.phone||'')} · LANGAME #${mgEsc(g.guest_id||g.id||'')}</div></section>`).join('')||'<div class="empty">Ничего не найдено</div>'}`)}
async function crmGroup(id){clear();setBottom(false);back();const d=await api('/api/crm/guests?group_id='+id+'&q=');const items=d.data?.data||d.data?.items||[];root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Гости группы</h2><span>${items.length}</span></div>${items.map(g=>`<section class="card"><div class="admin-name">${mgEsc(g.fio||'Без имени')}</div><div class="admin-meta">${mgEsc(g.phone||'')} · LANGAME #${mgEsc(g.guest_id||g.id||'')}</div></section>`).join('')||'<div class="empty">Гостей в группе нет</div>'}`)}
async function analytics(days=30){clear();setBottom(false);back();const d=await api('/api/analytics-plus?days='+days);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">ANALYTICS</div><div class="hero-title">Аналитика</div><div class="hero-sub">Динамика выручки и операций за выбранный период.</div></section>${mgPeriod('analytics')}<div class="kpis"><div class="kpi"><div class="kpi-label">Выручка</div><div class="kpi-value">${mgMoney(d.revenue.total)}</div></div><div class="kpi"><div class="kpi-label">Игровое время</div><div class="kpi-value">${mgMoney(d.revenue.gaming)}</div></div><div class="kpi"><div class="kpi-label">Бар</div><div class="kpi-value">${mgMoney(d.revenue.bar)}</div></div><div class="kpi"><div class="kpi-label">Единицы</div><div class="kpi-value">${d.units}</div></div></div><div class="section-title"><h2>По дням</h2><span>${days} дней</span></div><section class="card">${(d.daily||[]).map(x=>row(x.date,mgMoney(x.total),`Бар ${mgMoney(x.bar)} · Игровое ${mgMoney(x.gaming)}`)).join('')||'<div class="empty">Нет данных</div>'}</section><div class="card muted">Гости сейчас, число сессий и часы не подставляются из локальной БД: нужен подтверждённый read-only источник LANGAME.</div>`)}
async function finance(days=30){clear();setBottom(false);back();const d=await api('/api/finance-plus?days='+days);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">FINANCE</div><div class="hero-title">Финансы</div><div class="hero-sub">Доходы, закупки бара, зарплаты, штрафы и результат.</div></section>${mgPeriod('finance')}<div class="kpis"><div class="kpi"><div class="kpi-label">Доход</div><div class="kpi-value">${mgMoney(d.revenue.total)}</div></div><div class="kpi"><div class="kpi-label">Закупка бара</div><div class="kpi-value">${mgMoney(d.expenses.bar_purchases)}</div></div><div class="kpi"><div class="kpi-label">Зарплаты</div><div class="kpi-value">${mgMoney(d.expenses.salary)}</div></div><div class="kpi"><div class="kpi-label">Результат</div><div class="kpi-value ${d.profit>=0?'good':'bad'}">${mgMoney(d.profit)}</div></div></div><section class="card">${row('Игровое время',mgMoney(d.revenue.gaming))}${row('Бар и снеки',mgMoney(d.revenue.bar))}${row('Всего',mgMoney(d.revenue.total))}</section><div class="section-title"><h2>Расходы</h2></div><section class="card">${row('Закупки бара',mgMoney(d.expenses.bar_purchases))}${row('Зарплаты',mgMoney(d.expenses.salary))}${row('Штрафы',mgMoney(d.expenses.penalties))}${row('Всего',mgMoney(d.expenses.total))}</section><div class="section-title"><h2>Смены</h2></div><section class="card">${(d.shifts||[]).map(s=>row(mgEsc(s.employee),mgMoney(s.cash+s.card+s.online),`Наличные ${mgMoney(s.cash)} · Карта ${mgMoney(s.card)} · Онлайн ${mgMoney(s.online)}`)).join('')||'<div class="empty">Нет смен</div>'}</section>`)}
async function workCenter(){clear();setBottom(false);back();const d=await api('/api/work-center');root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">То, что требует действия прямо сейчас.</div></section><div class="section-title"><h2>Смены сейчас</h2><span>${d.shifts.length}</span></div><section class="card">${d.shifts.map(s=>row(mgEsc(s.employee),mgMoney(s.sales),new Date(s.started_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}))).join('')||'<div class="empty">Нет открытых смен</div>'}</section><div class="section-title"><h2>Критические остатки</h2><span>${d.critical_stock.length}</span></div><section class="card">${d.critical_stock.map(x=>row(mgEsc(x.product),`${x.quantity}`,`${mgEsc(x.club)} · минимум ${x.min_stock}`)).join('')||'<div class="empty">Критических остатков нет</div>'}</section><div class="section-title"><h2>Открытые смены без отчёта</h2><span>${d.open_without_report.length}</span></div><section class="card">${d.open_without_report.map(x=>row(mgEsc(x.employee),'Нужен отчёт')).join('')||'<div class="empty">Все отчёты в порядке</div>'}</section><div class="card muted">Гости сейчас, активные сессии и загрузка зала будут подключены только после подтверждённого read-only источника LANGAME.</div>`)}
const mgLegacyGoNav=goNav;goNav=function(which){if(which==='work'&&me?.role==='owner')workCenter();else mgLegacyGoNav(which)};
if(typeof me!=='undefined'&&me){setTimeout(()=>{if(me.role==='owner')home()},0)}
</script>'''


async def _index():
    response = await current_summary_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    web_app.add_api_route("/api/crm/overview", _crm_overview, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/crm/guests", _crm_guests, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/analytics-plus", _analytics_plus, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/finance-plus", _finance_plus, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center", _work_center, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
