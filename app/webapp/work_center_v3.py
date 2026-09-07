from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, ProductCategory, Club, Shift, ShiftCloseReport, ShiftCloseStockItem
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
        if isinstance(payload, dict):
            p = payload.get("pagination") or {}
            last = payload.get("total_pages") or p.get("total_pages") or p.get("last_page")
            if last and page >= int(last):
                break
        page += 1
    return rows


def _money(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _wall(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).isoformat()


def _active(row):
    try:
        return int(row.get("normal_stop", 1) or 0) == 0
    except (TypeError, ValueError):
        return str(row.get("normal_stop")).lower() in {"false", "0", "no"}


async def _active_sessions(now):
    local = now.astimezone(MSK)
    today = local.date()
    rows = await _all_pages(langame_client.guest_sessions, (today - timedelta(days=1)).isoformat(), today.isoformat())
    return [r for r in rows if _active(r) and r.get("guest_id") is not None]


async def _guest_names(ids):
    result = {}
    for guest_id in sorted({int(x) for x in ids if x is not None}):
        try:
            payload = await langame_client.guest_by_id(guest_id)
            row = _rows(payload)[0] if _rows(payload) else {}
            result[guest_id] = row.get("fio") or row.get("name") or row.get("phone") or f"Гость #{guest_id}"
        except LangameAPIError:
            result[guest_id] = f"Гость #{guest_id}"
    return result


async def _finance_period(start, end):
    local_start = start.astimezone(MSK)
    local_end = end.astimezone(MSK)
    date_from = local_start.date().isoformat()
    date_to = local_end.date().isoformat()
    balances = await _all_pages(langame_client.balances, date_from, date_to)
    products = await _all_pages(langame_client.product_sales, date_from, date_to)
    gaming = sum(max(0.0, _money(r.get("amount"))) for r in balances)
    bar = sum(max(0.0, _money(r.get("price_sale")) * _money(r.get("count"))) for r in products if not int(r.get("cancel", 0) or 0))
    return {"gaming": gaming, "bar": bar, "total": gaming + bar, "from": date_from, "to": date_to}


async def _work(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        open_shifts = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        critical = (await session.execute(select(InventoryBalance, Product, Club, ProductCategory).join(Product, Product.id == InventoryBalance.product_id).outerjoin(ProductCategory, ProductCategory.id == Product.category_id).join(Club, Club.id == InventoryBalance.club_id).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock).order_by(InventoryBalance.quantity))).all()
        reports = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_not(None)).order_by(Shift.ended_at.desc()).limit(100))).all()
        open_reports = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.ended_at.is_(None)))).all()
    try:
        active = await _active_sessions(now)
        names = await _guest_names([r.get("guest_id") for r in active])
        sessions_error = False
    except LangameAPIError:
        active, names, sessions_error = [], {}, True
    try:
        bar = await bar_report(datetime(2020, 1, 1, tzinfo=MSK), now)
    except LangameAPIError:
        bar = {"sales": None, "purchases": None, "profit": None}
    categories = {}
    for balance, product, club, category in critical:
        name = category.name if category else "Без категории"
        bucket = categories.setdefault(name, {"id": category.id if category else 0, "name": name, "count": 0})
        bucket["count"] += 1
    return {"updated_at": now.astimezone(MSK).isoformat(), "hall": {"active_guests": None if sessions_error else len({int(s["guest_id"]) for s in active})}, "guests_now": [{"guest_id": int(s["guest_id"]), "fio": names.get(int(s["guest_id"]), f"Гость #{s['guest_id']}"), "session_id": s.get("id"), "started_at": s.get("date_start"), "pc": s.get("pc") or s.get("pc_name") or s.get("computer")} for s in active], "bar": {"sales": bar.get("sales"), "purchases": bar.get("purchases"), "profit": bar.get("profit")}, "shifts": [{"id": s.id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": _wall(s.started_at), "sales": _money(s.cash_sales) + _money(s.card_sales) + _money(s.mobile_sales), "cash": _money(s.cash_sales), "card": _money(s.card_sales), "online": _money(s.mobile_sales)} for s, e in open_shifts], "reports": [{"id": report.id if report else None, "shift_id": shift.id, "employee_id": shift.employee_id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "started_at": _wall(shift.started_at), "ended_at": _wall(shift.ended_at), "status": report.status if report else "missing", "sales": _money(shift.cash_sales) + _money(shift.card_sales) + _money(shift.mobile_sales), "cash_difference": _money(shift.cash_difference) if shift.cash_difference is not None else None} for shift, employee, report in reports], "warehouse": {"critical": len(critical), "categories": list(categories.values())}, "control": {"open_without_report": sum(1 for _, _, r in open_reports if not r or r.status != "submitted"), "critical_stock": len(critical)}}


async def _shift_report(request: Request, report_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        result = (await session.execute(select(ShiftCloseReport, Shift, Employee, Club).join(Shift, Shift.id == ShiftCloseReport.shift_id).outerjoin(Employee, Employee.id == Shift.employee_id).outerjoin(Club, Club.id == Shift.club_id).where(ShiftCloseReport.id == report_id))).first()
        if not result:
            raise HTTPException(404, "Shift report not found")
        report, shift, employee, club = result
        items = (await session.execute(select(ShiftCloseStockItem, Product).join(Product, Product.id == ShiftCloseStockItem.product_id).where(ShiftCloseStockItem.report_id == report.id).order_by(Product.name))).all()
    return {"id": report.id, "shift_id": shift.id, "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}", "club": club.name if club else "—", "started_at": _wall(shift.started_at), "ended_at": _wall(shift.ended_at), "status": report.status, "cash_expected": _money(report.cash_expected), "cash_actual": _money(report.cash_actual) if report.cash_actual is not None else None, "cash_difference": _money(report.cash_difference) if report.cash_difference is not None else None, "cash_shortage_reason": report.cash_shortage_reason, "cash_comment": report.cash_comment, "stock_items_count": report.stock_items_count, "stock_discrepancies_count": report.stock_discrepancies_count, "handover_note": shift.handover_note, "items": [{"product": product.name, "langame_quantity": _money(item.langame_quantity), "actual_quantity": _money(item.actual_quantity) if item.actual_quantity is not None else None, "difference": _money(item.difference) if item.difference is not None else None, "shortage_reason": item.shortage_reason, "comment": item.comment} for item, product in items]}


async def _finance_api(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc).astimezone(MSK)
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    try:
        start = datetime.fromisoformat(date_from).replace(tzinfo=MSK) if date_from else now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = datetime.fromisoformat(date_to).replace(tzinfo=MSK) if date_to else now
        if end < start:
            raise HTTPException(400, "date_to must be >= date_from")
        finance = await _finance_period(start, end)
        bar = await bar_report(start, end)
        finance.update({"bar_sales": bar.get("sales"), "bar_purchases": bar.get("purchases"), "bar_profit": bar.get("profit")})
        return finance
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME finance unavailable: {exc}") from exc


async def _critical_api(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(select(InventoryBalance, Product, Club, ProductCategory).join(Product, Product.id == InventoryBalance.product_id).outerjoin(ProductCategory, ProductCategory.id == Product.category_id).join(Club, Club.id == InventoryBalance.club_id).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock).order_by(InventoryBalance.quantity))).all()
    return {"items": [{"id": b.id, "product": p.name, "category": c.name if c else "Без категории", "club": club.name, "quantity": _money(b.quantity), "min_stock": _money(b.min_stock)} for b, p, club, c in rows]}


async def _category_api(request: Request, category_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        query = select(InventoryBalance, Product, Club).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id)
        if category_id:
            query = query.where(Product.category_id == category_id)
        rows = (await session.execute(query.order_by(Product.name))).all()
    return {"category_id": category_id, "items": [{"id": b.id, "product": p.name, "club": club.name, "quantity": _money(b.quantity), "min_stock": _money(b.min_stock)} for b, p, club in rows]}


JS = r'''<script>
function wcMoney(v){return v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽'}
function wcEsc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function wcTime(v){return v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—'}
function wcRow(t,v){return `<div class="row"><div class="row-main"><div class="row-title">${wcEsc(t)}</div></div><div class="row-value">${wcEsc(v)}</div></div>`}
function wcBack(){root.prepend(btn('← Назад',workCenter,'back'))}
async function workGuestsNow(){clear();setBottom(false);const d=await api('/api/work-center-v3');root.innerHTML=`<section class="hero"><div class="eyebrow">ЗАЛ · ГОСТИ СЕЙЧАС</div><div class="hero-title">Гости сейчас</div></section><div class="nav-card">${(d.guests_now||[]).map(g=>`<button class="nav-btn" onclick="crmGuestOpen(${Number(g.guest_id)})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">${wcEsc(g.fio)}</span><span class="nav-hint">С ${wcTime(g.started_at)}${g.pc?' · '+wcEsc(g.pc):''}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Активных гостей сейчас нет</div>'}</div>`;wcBack()}
async function shiftReportOpen(id){if(!id)return;clear();setBottom(false);const d=await api('/api/work-center-v3/reports/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ОТЧЁТ О СМЕНЕ</div><div class="hero-title">${wcEsc(d.employee)}</div><div class="hero-sub">${wcTime(d.started_at)} — ${wcTime(d.ended_at)} · ${wcEsc(d.club)}</div></section><section class="card">${wcRow('Статус',d.status==='submitted'?'Сдан':'Не завершён')}${wcRow('Расчётная наличность',wcMoney(d.cash_expected))}${wcRow('Фактическая наличность',wcMoney(d.cash_actual))}${wcRow('Разница кассы',d.cash_difference==null?'—':wcMoney(d.cash_difference))}${wcRow('Проверено товаров',d.stock_items_count??'—')}${wcRow('Расхождений по товарам',d.stock_discrepancies_count??0)}${d.handover_note?wcRow('Передача смены',d.handover_note):''}</section>`;wcBack()}
async function shiftReports(){clear();setBottom(false);const d=await api('/api/work-center-v3');root.innerHTML=`<section class="hero"><div class="eyebrow">РАБОТА · ОТЧЁТЫ</div><div class="hero-title">Отчёты о сменах</div></section><div class="nav-card">${(d.reports||[]).map(r=>`<button class="nav-btn" onclick="shiftReportOpen(${Number(r.id||0)})"><span class="nav-icon">${r.status==='submitted'?'📋':'⚠️'}</span><span class="nav-copy"><span class="nav-label">${wcEsc(r.employee)}</span><span class="nav-hint">${wcTime(r.started_at)} — ${wcTime(r.ended_at)} · ${r.status==='submitted'?'Отчёт сдан':'Требует внимания'}</span></span><span class="nav-arrow">${wcMoney(r.sales)}</span></button>`).join('')||'<div class="empty">Отчётов о сменах пока нет</div>'}</div>`;wcBack()}
async function workFinance(){clear();setBottom(false);const today=new Date().toISOString().slice(0,10);root.innerHTML=`<section class="hero"><div class="eyebrow">ФИНАНСЫ</div><div class="hero-title">Баланс аккаунтов · Еда и услуги</div></section><section class="card"><div class="row"><div class="row-main"><div class="row-title">От</div></div><input id="finFrom" type="date" value="${today}"></div><div class="row"><div class="row-main"><div class="row-title">До</div></div><input id="finTo" type="date" value="${today}"></div><button class="primary" onclick="loadFinance()">Показать период</button></section><div id="finOut"></div>`;await loadFinance()}
async function loadFinance(){const f=document.getElementById('finFrom')?.value,t=document.getElementById('finTo')?.value;if(!f||!t)return;const d=await api(`/api/work-center-v3/finance?date_from=${f}&date_to=${t}`);document.getElementById('finOut').innerHTML=`<section class="card">${wcRow('Баланс аккаунтов',wcMoney(d.gaming))}${wcRow('Еда и услуги',wcMoney(d.bar_sales))}${wcRow('Итого',wcMoney(d.total))}${wcRow('Закупки по приходам',wcMoney(d.bar_purchases))}${wcRow('Прибыль бара',wcMoney(d.bar_profit))}</section>`}
async function workWarehouse(){clear();setBottom(false);const d=await api('/api/work-center-v3');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Склад по категориям</div></section><div class="nav-card">${(d.warehouse?.categories||[]).map(c=>`<button class="nav-btn" onclick="warehouseCategory(${Number(c.id)})"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${wcEsc(c.name)}</span><span class="nav-hint">${c.count} позиций</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Категории склада не найдены</div>'}</div><button class="primary" onclick="criticalStock()">Критические остатки</button>`;wcBack()}
async function warehouseCategory(id){clear();setBottom(false);const d=await api('/api/work-center-v3/categories/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД · КАТЕГОРИЯ</div><div class="hero-title">Товары</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${wcEsc(x.product)}</div><div class="row-sub">${wcEsc(x.club)}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')||'<div class="empty">В категории нет товаров</div>'}</div>`;wcBack()}
async function criticalStock(){clear();setBottom(false);const d=await api('/api/work-center-v3/critical');root.innerHTML=`<section class="hero"><div class="eyebrow">КРИТИЧЕСКИЕ ОСТАТКИ</div><div class="hero-title">${(d.items||[]).length} позиций</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${wcEsc(x.product)}</div><div class="row-sub">${wcEsc(x.category)} · ${wcEsc(x.club)}</div></div><div class="row-value">${x.quantity} / ${x.min_stock}</div></div>`).join('')||'<div class="empty">Критических остатков нет</div>'}</div>`;wcBack()}
async function workControl(){clear();setBottom(false);const d=await api('/api/work-center-v3');const c=d.control||{};root.innerHTML=`<section class="hero"><div class="eyebrow">КОНТРОЛЬ</div><div class="hero-title">Что требует действия</div></section><div class="nav-card">${c.open_without_report?`<button class="nav-btn" onclick="shiftReports()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Смены без отчёта</span><span class="nav-hint">${c.open_without_report}</span></span><span class="nav-arrow">›</span></button>`:''}${c.critical_stock?`<button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${c.critical_stock}</span></span><span class="nav-arrow">›</span></button>`:''}${!(c.open_without_report||c.critical_stock)?'<div class="empty">Критических действий нет</div>':''}</div>`;wcBack()}
async function workCenter(){clear();setBottom(false);back();const d=await api('/api/work-center-v3');root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель.</div><div class="row-sub">Обновлено ${wcTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Зал</h2></div><section class="card"><button class="nav-btn" onclick="workGuestsNow()"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">Гости сейчас</span><span class="nav-hint">Активные сессии · ${d.hall.active_guests??'—'}</span></span><span class="nav-arrow">›</span></button></section><div class="section-title"><h2>Бар и снеки</h2><span>Прибыль</span></div><section class="card">${wcRow('Прибыль',wcMoney(d.bar.profit))}</section><div class="section-title"><h2>Финансы</h2></div><div class="nav-card"><button class="nav-btn" onclick="workFinance()"><span class="nav-icon">💰</span><span class="nav-copy"><span class="nav-label">Финансы</span><span class="nav-hint">Баланс аккаунтов · Еда и услуги · произвольный период</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Отчёты о сменах</h2><span>${(d.reports||[]).length}</span></div><div class="nav-card"><button class="nav-btn" onclick="shiftReports()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Открыть отчёты о сменах</span><span class="nav-hint">Касса · остатки · передача смены</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Склад</h2><span>${d.warehouse.critical}</span></div><div class="nav-card"><button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Полный склад</span><span class="nav-hint">Категории</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${d.warehouse.critical} позиций</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Контроль</h2><span>${d.control.open_without_report+d.control.critical_stock}</span></div><div class="nav-card"><button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Открыть контроль</span></span><span class="nav-arrow">›</span></button></div>`}
</script>'''


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path in ("/api/work-center-v2","/api/work-center-v3","/api/work-center-v3/reports/{report_id}","/api/work-center-v3/finance","/api/work-center-v3/critical","/api/work-center-v3/categories/{category_id}"):
            web_app.routes.remove(route)
    web_app.add_api_route("/api/work-center-v3", _work, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v3/reports/{report_id}", _shift_report, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v3/finance", _finance_api, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v3/critical", _critical_api, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/work-center-v3/categories/{category_id}", _category_api, methods=["GET"], include_in_schema=False)
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
