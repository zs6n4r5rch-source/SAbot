from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, ProductCategory, Club, SalaryViolation, Shift, ShiftCloseReport, ShiftCloseStockItem
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required
from app.webapp.bar_finance import report as bar_report

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


async def _all_pages(method, *args, **kwargs):
    rows, page = [], 1
    while page <= 50:
        payload = await method(*args, page=page, page_limit=500, **kwargs)
        batch = [x for x in _rows(payload) if isinstance(x, dict)]
        if not batch:
            break
        rows.extend(batch)
        pagination = payload.get("pagination") or {} if isinstance(payload, dict) else {}
        total_pages = payload.get("total_pages") if isinstance(payload, dict) else None
        total_pages = total_pages or pagination.get("total_pages")
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
    all_time_start = datetime(2000, 1, 1, tzinfo=MSK)
    day = now.astimezone(MSK).date().isoformat()

    async with SessionLocal() as session:
        open_shifts = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        critical = (await session.execute(select(InventoryBalance, Product, Club, ProductCategory).join(Product, Product.id == InventoryBalance.product_id).outerjoin(ProductCategory, ProductCategory.id == Product.category_id).join(Club, Club.id == InventoryBalance.club_id).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock).order_by(InventoryBalance.quantity))).all()
        reports = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_not(None)).order_by(Shift.ended_at.desc()).limit(50))).all()
        open_reports = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_(None)))).all()
        violations = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0

    sessions = []
    sessions_error = False
    try:
        sessions = await _all_pages(langame_client.guest_sessions, day, day)
    except LangameAPIError:
        sessions_error = True
    active = [s for s in sessions if int(s.get("normal_stop", 1) or 0) == 0 and s.get("guest_id") is not None]

    try:
        bar = await bar_report(all_time_start, now)
    except LangameAPIError:
        bar = {"sales": None, "purchases": None, "profit": None, "products": []}

    hall = {}
    if not sessions_error:
        hall["active_guests"] = len({int(s["guest_id"]) for s in active})

    categories = {}
    for balance, product, club, category in critical:
        name = category.name if category else "Без категории"
        bucket = categories.setdefault(name, {"name": name, "count": 0})
        bucket["count"] += 1

    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "hall": hall,
        "guests_now": [{"guest_id": int(s["guest_id"]), "session_id": s.get("id"), "started_at": s.get("date_start"), "ended_at": s.get("date_stop"), "pc": s.get("pc") or s.get("pc_name") or s.get("computer")} for s in active],
        "bar": {"sales": bar.get("sales"), "purchases": bar.get("purchases"), "profit": bar.get("profit"), "products": (bar.get("products") or [])[:10], "basis": "Все время"},
        "shifts": [{"id": s.id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": _wall(s.started_at), "sales": _money(s.cash_sales) + _money(s.card_sales) + _money(s.mobile_sales), "cash": _money(s.cash_sales), "card": _money(s.card_sales), "online": _money(s.mobile_sales)} for s, e in open_shifts],
        "reports": [{"id": report.id if report else None, "shift_id": shift.id, "employee_id": shift.employee_id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "started_at": _wall(shift.started_at), "ended_at": _wall(shift.ended_at), "status": report.status if report else "missing", "sales": _money(shift.cash_sales) + _money(shift.card_sales) + _money(shift.mobile_sales), "cash_difference": _money(shift.cash_difference) if shift.cash_difference is not None else None} for shift, employee, report in reports],
        "warehouse": {"critical": len(critical), "categories": list(categories.values())},
        "control": {"open_without_report": sum(1 for _, _, r in open_reports if not r or r.status != "submitted"), "violations": int(violations), "critical_stock": len(critical)},
    }


async def _shift_report(request: Request, report_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        result = (await session.execute(select(ShiftCloseReport, Shift, Employee, Club).join(Shift, Shift.id == ShiftCloseReport.shift_id).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(Club, Club.id == Shift.club_id).where(ShiftCloseReport.id == report_id))).first()
        if not result:
            raise HTTPException(404, "Shift report not found")
        report, shift, employee, club = result
        items = (await session.execute(select(ShiftCloseStockItem, Product).join(Product, Product.id == ShiftCloseStockItem.product_id).where(ShiftCloseStockItem.report_id == report.id).order_by(Product.name))).all()
    return {"id": report.id, "shift_id": shift.id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "club": club.name if club else "—", "started_at": _wall(shift.started_at), "ended_at": _wall(shift.ended_at), "status": report.status, "cash_expected": _money(report.cash_expected), "cash_actual": _money(report.cash_actual) if report.cash_actual is not None else None, "cash_difference": _money(report.cash_difference) if report.cash_difference is not None else None, "cash_shortage_reason": report.cash_shortage_reason, "cash_comment": report.cash_comment, "stock_items_count": report.stock_items_count, "stock_discrepancies_count": report.stock_discrepancies_count, "handover_note": shift.handover_note, "cleaning_confirmed_at": _wall(report.cleaning_confirmed_at), "items": [{"product": product.name, "langame_quantity": _money(item.langame_quantity), "actual_quantity": _money(item.actual_quantity) if item.actual_quantity is not None else None, "difference": _money(item.difference) if item.difference is not None else None, "shortage_reason": item.shortage_reason, "comment": item.comment} for item, product in items]}


JS = r'''<script>
function wcMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function wcEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function wcTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
function wcRow(t,v){return `<div class="row"><div class="row-main"><div class="row-title">${wcEsc(t)}</div></div><div class="row-value">${wcEsc(v)}</div></div>`}
function wcBack(){root.prepend(btn('← Назад',workCenter,'back'))}
async function workGuestsNow(){clear();setBottom(false);const d=await api('/api/work-center-v3');const guests=d.guests_now||[];root.innerHTML=`<section class="hero"><div class="eyebrow">ЗАЛ · ГОСТИ СЕЙЧАС</div><div class="hero-title">Гости сейчас</div><div class="hero-sub">Только активные сессии LANGAME.</div></section><div class="section-title"><h2>Активные гости</h2><span>${guests.length}</span></div><div class="nav-card">${guests.map(g=>`<button class="nav-btn" onclick="crmGuestOpen(${Number(g.guest_id)})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">Гость #${Number(g.guest_id)}</span><span class="nav-hint">С ${wcTime(g.started_at)}${g.pc?' · '+wcEsc(g.pc):''}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Активных гостей сейчас нет</div>'}</div>`;wcBack()}
async function shiftReportOpen(id){if(!id){alert('Отчёт ещё не создан');return}clear();setBottom(false);const d=await api('/api/work-center-v3/reports/'+Number(id));const bad=(d.items||[]).filter(x=>x.difference!=null&&Number(x.difference)!==0);root.innerHTML=`<section class="hero"><div class="eyebrow">ОТЧЁТ О СМЕНЕ</div><div class="hero-title">${wcEsc(d.employee)}</div><div class="hero-sub">${wcTime(d.started_at)} — ${wcTime(d.ended_at)} · ${wcEsc(d.club)}</div></section><section class="card">${wcRow('Статус',d.status==='submitted'?'Сдан':'Не завершён')}${wcRow('Расчётная наличность',wcMoney(d.cash_expected))}${wcRow('Фактическая наличность',wcMoney(d.cash_actual))}${wcRow('Разница кассы',d.cash_difference==null?'—':wcMoney(d.cash_difference))}${wcRow('Проверено товаров',d.stock_items_count??'—')}${wcRow('Расхождений по товарам',d.stock_discrepancies_count??0)}${d.cash_shortage_reason?wcRow('Причина недостачи',d.cash_shortage_reason):''}${d.cash_comment?wcRow('Комментарий по кассе',d.cash_comment):''}${d.handover_note?wcRow('Передача смены',d.handover_note):''}</section><div class="section-title"><h2>Расхождения товаров</h2><span>${bad.length}</span></div><div class="nav-card">${bad.map(x=>`<div class="row"><div class="row-main"><div class="row-title">${wcEsc(x.product)}</div><div class="row-sub">LANGAME ${x.langame_quantity} → факт ${x.actual_quantity} · ${wcEsc(x.shortage_reason||x.comment||'Без комментария')}</div></div><div class="row-value">${x.difference>0?'+':''}${x.difference}</div></div>`).join('')||'<div class="empty">Расхождений нет</div>'}</div>`;wcBack()}
async function shiftReports(){clear();setBottom(false);const d=await api('/api/work-center-v3');const items=d.reports||[];root.innerHTML=`<section class="hero"><div class="eyebrow">РАБОТА · ОТЧЁТЫ</div><div class="hero-title">Отчёты о сменах</div><div class="hero-sub">Закрытые смены, касса, остатки и передача смены.</div></section><div class="nav-card">${items.map(r=>`<button class="nav-btn" onclick="shiftReportOpen(${Number(r.id||0)})"><span class="nav-icon">${r.status==='submitted'?'📋':'⚠️'}</span><span class="nav-copy"><span class="nav-label">${wcEsc(r.employee)}</span><span class="nav-hint">${wcTime(r.started_at)} — ${wcTime(r.ended_at)} · ${r.status==='submitted'?'Отчёт сдан':'Требует внимания'}</span></span><span class="nav-arrow">${wcMoney(r.sales)}</span></button>`).join('')||'<div class="empty">Отчётов о сменах пока нет</div>'}</div>`;wcBack()}
async function workWarehouse(){clear();setBottom(false);const d=await api('/api/work-center-v3');const cats=d.warehouse?.categories||[];root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Критические остатки</div><div class="hero-sub">Товары сгруппированы по категориям. Полный список открывается отдельно.</div></section><button class="primary" onclick="inventory()">Открыть полный склад</button><div class="section-title"><h2>Категории</h2><span>${d.warehouse?.critical||0} позиций</span></div><div class="nav-card">${cats.map(c=>`<div class="row"><div class="row-main"><div class="row-title">${wcEsc(c.name)}</div><div class="row-sub">${c.count} критических позиций</div></div><div class="row-value">›</div></div>`).join('')||'<div class="empty">Критических остатков нет</div>'}</div>`;wcBack()}
async function workControl(){clear();setBottom(false);const d=await api('/api/work-center-v3');const c=d.control||{};root.innerHTML=`<section class="hero"><div class="eyebrow">КОНТРОЛЬ</div><div class="hero-title">Что требует действия</div><div class="hero-sub">Только операционные контрольные пункты, без аналитики.</div></section><div class="nav-card">${c.open_without_report?`<button class="nav-btn" onclick="shiftReports()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Смены без отчёта</span><span class="nav-hint">${c.open_without_report}</span></span><span class="nav-arrow">›</span></button>`:''}${c.critical_stock?`<button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${c.critical_stock}</span></span><span class="nav-arrow">›</span></button>`:''}${c.violations?`<button class="nav-btn" onclick="attention()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Требует решения</span><span class="nav-hint">${c.violations}</span></span><span class="nav-arrow">›</span></button>`:''}${!(c.open_without_report||c.critical_stock||c.violations)?'<div class="empty">Критических действий нет</div>':''}</div>`;wcBack()}
async function workCenter(){clear();setBottom(false);back();const d=await api('/api/work-center-v3');const hall=d.hall||{};const reports=d.reports||[];root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель: что происходит и что требует действия сейчас.</div><div class="row-sub">Обновлено ${wcTime(d.updated_at)}, Москва.</div></section>${hall.active_guests!=null?`<div class="section-title"><h2>Зал</h2><span>LANGAME</span></div><section class="card"><button class="nav-btn" onclick="workGuestsNow()"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">Гости сейчас</span><span class="nav-hint">Активные сессии LANGAME · ${hall.active_guests}</span></span><span class="nav-arrow">›</span></button></section>`:''}<div class="section-title"><h2>Бар и снеки</h2><span>${wcEsc(d.bar?.basis||'Все время')}</span></div><section class="card">${wcRow('Продажи',wcMoney(d.bar.sales))}${wcRow('Закупка по приходам',wcMoney(d.bar.purchases))}${wcRow('Прибыль · продажа − закупка',wcMoney(d.bar.profit))}<button class="primary" onclick="finance()">Открыть финансы</button></section><div class="section-title"><h2>Отчёты о сменах</h2><span>${reports.length}</span></div><div class="nav-card"><button class="nav-btn" onclick="shiftReports()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Открыть отчёты о сменах</span><span class="nav-hint">Касса · остатки · передача смены</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Склад</h2><span>${d.warehouse.critical}</span></div><div class="nav-card"><button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">По категориям из базы</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="inventory()"><span class="nav-icon">🗃</span><span class="nav-copy"><span class="nav-label">Полный склад</span><span class="nav-hint">Открыть список товаров</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Контроль</h2><span>${d.control.open_without_report+d.control.violations+d.control.critical_stock}</span></div><div class="nav-card"><button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Открыть контроль</span><span class="nav-hint">Смены · остатки · решения</span></span><span class="nav-arrow">›</span></button></div>`}
</script>'''


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path in ("/api/work-center-v2", "/api/work-center-v3", "/api/work-center-v3/reports/{report_id}"):
            web_app.routes.remove(route)
    web_app.add_api_route("/api/work-center-v3", _work, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v3/reports/{report_id}", _shift_report, methods=["GET"], include_in_schema=False)
    root_route = next((r for r in web_app.routes if isinstance(r, APIRoute) and r.path == "/"), None)
    if root_route is None:
        return
    previous_endpoint = root_route.endpoint
    async def wrapped_root():
        response = await previous_endpoint()
        html = response.body.decode("utf-8")
        return HTMLResponse(html.replace("</body>", JS + "</body>", 1))
    web_app.routes.remove(root_route)
    web_app.add_api_route("/", wrapped_root, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is wrapped_root:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
