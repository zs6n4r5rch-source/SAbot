from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select, desc

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, Club, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required, dec
from app.webapp.management_dashboard import _guest_groups, _guest_group_count, _index as management_index
from app.webapp.bar_finance import report as bar_report

MSK = ZoneInfo("Europe/Moscow")


def _wall_time(value):
    # Shift timestamps in the local operational DB are stored as the club's
    # wall-clock time. Do not apply a second UTC->MSK conversion to display them.
    if value is None:
        return None
    return value.replace(tzinfo=MSK).isoformat()


async def _summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionLocal() as session:
        open_rows = (await session.execute(
            select(Shift, Employee)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.ended_at.is_(None))
            .order_by(Shift.started_at)
        )).all()
        today_rows = (await session.execute(
            select(Shift, Employee)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.started_at >= start)
            .order_by(desc(Shift.started_at))
        )).all()
        previous = None
        for shift, employee in today_rows:
            if shift.ended_at is not None:
                report = await session.scalar(select(ShiftCloseReport).where(ShiftCloseReport.shift_id == shift.id))
                previous = {
                    "id": shift.id,
                    "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}",
                    "started_at": _wall_time(shift.started_at),
                    "ended_at": _wall_time(shift.ended_at),
                    "status": report.status if report else "no_report",
                    "report_id": report.id if report else None,
                }
                break
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(
            InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock
        )) or 0
        dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(
            SalaryViolation.dismissal_required.is_(True)
        )) or 0
        shift_gross = sum(
            dec(s.cash_sales) + dec(s.card_sales) + dec(s.mobile_sales)
            for s, _ in today_rows
        )

    try:
        bar = await bar_report(start, now)
        bar_sales = float(bar.get("sales", 0) or 0)
    except LangameAPIError:
        bar_sales = 0.0

    # The product-expense endpoint is not the same metric as LANGAME BUSINESS
    # "Баланс аккаунтов". Until the exact read-only balance endpoint is wired,
    # use the already recorded daily live-money total from SAbot shifts and
    # subtract the independently calculated LANGAME bar sales.
    gaming = max(0.0, shift_gross - bar_sales)
    groups = []
    try:
        for g in await _guest_groups():
            groups.append({**g, "count": await _guest_group_count(g["id"])})
    except LangameAPIError:
        groups = []

    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "shifts": [{
            "id": s.id,
            "employee": e.full_name if e else f"Администратор #{s.employee_id}",
            "started_at": _wall_time(s.started_at),
            "sales": dec(s.cash_sales) + dec(s.card_sales) + dec(s.mobile_sales),
        } for s, e in open_rows],
        "previous_report": previous,
        "sales": {"bar": bar_sales, "gaming": gaming, "total": bar_sales + gaming, "source": "shift live money + LANGAME bar sales"},
        "guests": {"active": None, "today": None, "note": "Нужен подтверждённый read-only endpoint LANGAME для «С активной сессией» и «Были сегодня»."},
        "groups": groups,
        "attention": {"critical_stock": int(critical), "dismissal_required": int(dismissals), "critical_total": int(critical) + int(dismissals)},
    }


async def _work(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionLocal() as session:
        open_rows = (await session.execute(
            select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.ended_at.is_(None)).order_by(Shift.started_at)
        )).all()
        critical = (await session.execute(
            select(InventoryBalance, Product, Club)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Club, Club.id == InventoryBalance.club_id)
            .where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)
            .order_by(InventoryBalance.quantity)
        )).all()
        open_without_report = (await session.execute(
            select(Shift, Employee, ShiftCloseReport)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id)
            .where(Shift.ended_at.is_(None))
        )).all()
        previous = (await session.execute(
            select(Shift, Employee, ShiftCloseReport)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id)
            .where(Shift.ended_at.is_not(None))
            .order_by(desc(Shift.ended_at)).limit(1)
        )).first()
    try:
        bar = await bar_report(start, now)
    except LangameAPIError:
        bar = {"sales": 0, "purchases": 0, "profit": 0, "products": []}
    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "hall": {"active_guests": None, "sessions": None, "load": None, "source": "LANGAME endpoint pending"},
        "bar": {"sales": float(bar.get("sales", 0) or 0), "purchases": float(bar.get("purchases", 0) or 0), "profit": float(bar.get("profit", 0) or 0), "products": bar.get("products", [])[:10]},
        "shifts": [{"id": s.id, "employee": e.full_name if e else f"#{s.employee_id}", "started_at": _wall_time(s.started_at), "sales": dec(s.cash_sales) + dec(s.card_sales) + dec(s.mobile_sales)} for s, e in open_rows],
        "warehouse": {"critical": len(critical), "items": [{"product": p.name, "club": c.name, "quantity": dec(b.quantity), "min_stock": dec(b.min_stock)} for b, p, c in critical]},
        "control": {"open_without_report": sum(1 for s, _, r in open_without_report if not r or r.status != "submitted"), "previous_report": previous[2].status if previous and previous[2] else "no_report"},
    }


JS = r'''<script>
function saMoney(v){return Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function saEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function saTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
async function home(){if(me?.role!=='owner'){return legacyCurrentSummaryHome?.()};clear();setBottom(true);const d=await api('/api/current-summary-v2');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn" onclick="adminShiftOpen(${s.id})"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${saEsc(s.employee)}</span><span class="nav-hint">С ${saTime(s.started_at)}</span></span><span class="nav-arrow">${saMoney(s.sales)}</span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${g.id})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${saEsc(g.name)}</span><span class="nav-hint">${g.count} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');const pr=d.previous_report;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${saTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="grid"><section class="card"><div class="section-title"><h2>Выручка сегодня</h2></div>${row('Бар и снеки',saMoney(d.sales.bar))}${row('Игровое время',d.sales.gaming===null?'—':saMoney(d.sales.gaming))}${row('Всего',saMoney(d.sales.total))}<div class="row-sub">${saEsc(d.sales.source)}</div></section><section class="card"><div class="section-title"><h2>Гости</h2><span>LANGAME</span></div>${row('Гости сейчас · активная сессия',d.guests.active??'—')}${row('Гости сегодня',d.guests.today??'—')}</section></div><div class="section-title"><h2>Гости и лояльность</h2><span>LANGAME</span></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Отчёт предыдущей смены</h2><span>1</span></div><div class="nav-card">${pr?`<button class="nav-btn" onclick="adminShiftOpen(${pr.id})"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">${saEsc(pr.employee)}</span><span class="nav-hint">${saTime(pr.started_at)} — ${saTime(pr.ended_at)} · ${saEsc(pr.status)}</span></span><span class="nav-arrow">›</span></button>`:'<div class="empty">Предыдущей закрытой смены сегодня нет</div>'}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${iconNav('📦','Критические остатки',String(d.attention.critical_stock),()=>inventory()).outerHTML}${iconNav('⚠️','Требуется решение',String(d.attention.dismissal_required),()=>attention()).outerHTML}</div>`}
async function adminShiftOpen(id){clear();setBottom(false);back();const d=await api('/api/admins');const a=(d.items||[]).find(x=>x.id===id);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">СМЕНА</div><div class="hero-title">${saEsc(a?.name||'Администратор')}</div><div class="hero-sub">Открытая смена и отчёт.</div></section><button class="primary" onclick="admins()">Открыть администратора</button>`)}
async function workCenter(){clear();setBottom(false);back();const d=await api('/api/work-center-v2');root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">То, что требует действия прямо сейчас.</div><div class="row-sub">Обновлено ${saTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Зал</h2><span>LANGAME</span></div><div class="grid"><section class="card">${row('Гости сейчас',d.hall.active_guests??'—')}${row('Активные сессии',d.hall.sessions??'—')}${row('Загрузка',d.hall.load??'—')}</section><section class="card"><div class="admin-name">Гости и сессии</div><div class="row-sub">Источник активных сессий LANGAME подключаем после подтверждения endpoint.</div></section></div><div class="section-title"><h2>Гости сейчас</h2><span>активные сессии</span></div><section class="card"><div class="kpi-value">${d.hall.active_guests??'—'}</div><div class="row-sub">Кто сейчас в клубе, ПК, оставшееся время и группа лояльности.</div></section><div class="section-title"><h2>Бар и снеки</h2><span>сегодня</span></div><section class="card">${row('Продажи',saMoney(d.bar.sales))}${row('Приходы / закупка',saMoney(d.bar.purchases))}${row('Прибыль',saMoney(d.bar.profit))}<button class="primary" onclick="finance()">Открыть финансы</button></section><div class="section-title"><h2>Смены</h2><span>${d.shifts.length}</span></div><div class="nav-card">${d.shifts.map(s=>`<button class="nav-btn" onclick="admins()"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${saEsc(s.employee)}</span><span class="nav-hint">С ${saTime(s.started_at)}</span></span><span class="nav-arrow">${saMoney(s.sales)}</span></button>`).join('')||'<div class="empty">Открытых смен нет</div>'}</div><div class="section-title"><h2>Склад</h2><span>${d.warehouse.critical}</span></div><div class="nav-card">${d.warehouse.items.map(x=>`<button class="nav-btn" onclick="inventory()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${saEsc(x.product)}</span><span class="nav-hint">${saEsc(x.club)} · ${x.quantity} / минимум ${x.min_stock}</span></span><span class="nav-arrow">⚠️</span></button>`).join('')||'<div class="empty">Критических остатков нет</div>'}</div><div class="section-title"><h2>Контроль</h2><span>${d.control.open_without_report}</span></div><div class="nav-card">${iconNav('📋','Смены без отчёта',String(d.control.open_without_report),()=>admins()).outerHTML}${iconNav('⚠️','Требует внимания',String(d.control.previous_report==='submitted'?0:1),()=>attention()).outerHTML}${iconNav('📦','Инвентарь',String(d.warehouse.critical),()=>inventory()).outerHTML}</div>`)}
</script>'''


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    web_app.add_api_route("/api/current-summary-v2", _summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v2", _work, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
