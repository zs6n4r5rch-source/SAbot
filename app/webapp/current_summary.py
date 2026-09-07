from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import (
    Employee,
    Guest,
    GuestGroup,
    GuestGroupMember,
    InventoryBalance,
    SalaryViolation,
    Shift,
    ShiftCloseReport,
)
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, dec, iso, owner_required


def _classify_sale(row: dict, product_map: dict[int, tuple[str, str]]) -> str:
    raw_id = row.get("product_id", row.get("productId", row.get("id")))
    try:
        pid = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        pid = None
    name = str(row.get("product_name") or row.get("productName") or row.get("name") or "").lower()
    category = ""
    if pid is not None and pid in product_map:
        name = f"{name} {product_map[pid][0]}".lower()
        category = product_map[pid][1].lower()
    text = f"{name} {category}"
    if any(x in text for x in ("бар", "снек", "напит", "еда", "кофе", "чай", "пицц", "бургер")):
        return "bar"
    if any(x in text for x in ("игров", "время", "тариф", "час", "аренд", "pc", "vip", "компьют")):
        return "gaming"
    return "other"


async def _sales_today():
    now = datetime.now(timezone.utc)
    try:
        products = await langame_client.products()
        product_map = {}
        for p in products.get("data") or products.get("items") or []:
            try:
                pid = int(p.get("id", p.get("product_id", p.get("langame_product_id"))))
            except (TypeError, ValueError):
                continue
            product_map[pid] = (
                str(p.get("name") or ""),
                str(p.get("category_name") or p.get("category") or ""),
            )
        rows = []
        page = 1
        while True:
            result = await langame_client.product_sales(
                now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), page=page, page_limit=100
            )
            batch = result.get("data") or result.get("items") or []
            if not batch:
                break
            rows.extend(batch)
            total_pages = result.get("total_pages")
            if not total_pages or page >= int(total_pages):
                break
            page += 1
        totals = {"bar": 0.0, "gaming": 0.0, "other": 0.0}
        units = 0.0
        for row in rows:
            if int(row.get("cancel", 0) or 0) == 1:
                continue
            try:
                qty = float(row.get("count", row.get("quantity", 0)) or 0)
                amount = float(row.get("price_sale", row.get("price", 0)) or 0) * qty
            except (TypeError, ValueError):
                continue
            units += qty
            totals[_classify_sale(row, product_map)] += amount
        return {"bar": totals["bar"], "gaming": totals["gaming"], "other": totals["other"], "units": units, "source": "langame"}
    except (LangameAPIError, TypeError, ValueError):
        return {"bar": 0.0, "gaming": 0.0, "other": 0.0, "units": 0.0, "source": "unavailable"}


async def _current_summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        open_rows = (await session.execute(
            select(Shift, Employee)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.ended_at.is_(None))
            .order_by(Shift.started_at)
        )).all()
        reports = (await session.execute(
            select(ShiftCloseReport, Shift, Employee)
            .join(Shift, Shift.id == ShiftCloseReport.shift_id)
            .outerjoin(Employee, Employee.id == Shift.employee_id)
            .where(Shift.started_at >= day_start)
        )).all()
        reports_submitted = sum(1 for r, _, _ in reports if r.status == "submitted")
        reports_pending = sum(1 for r, s, _ in reports if r.status != "submitted" and s.ended_at is not None)
        reports_missing = sum(1 for r, s, _ in reports if r.status != "submitted" and s.ended_at is None)
        critical_stock = await session.scalar(select(func.count(InventoryBalance.id)).where(
            InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock
        )) or 0
        pending_dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(
            SalaryViolation.dismissal_required.is_(True)
        )) or 0
        guests_total = await session.scalar(select(func.count(Guest.id))) or 0
        group_rows = (await session.execute(
            select(GuestGroup.id, GuestGroup.name, func.count(GuestGroupMember.guest_id))
            .outerjoin(GuestGroupMember, GuestGroupMember.guest_group_id == GuestGroup.id)
            .group_by(GuestGroup.id, GuestGroup.name)
            .order_by(desc(func.count(GuestGroupMember.guest_id)), GuestGroup.name)
        )).all()
    sales = await _sales_today()
    open_shifts = []
    for shift, employee in open_rows:
        elapsed = max(0, int((now - shift.started_at).total_seconds()))
        open_shifts.append({
            "id": shift.id,
            "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}",
            "started_at": iso(shift.started_at),
            "duration_minutes": elapsed // 60,
            "sales": dec(shift.cash_sales) + dec(shift.card_sales) + dec(shift.mobile_sales),
            "cash": dec(shift.cash_sales),
            "card": dec(shift.card_sales),
            "mobile": dec(shift.mobile_sales),
        })
    return {
        "updated_at": iso(now),
        "shifts": open_shifts,
        "reports": {"submitted": reports_submitted, "pending": reports_pending, "open_without_report": reports_missing},
        "sales": sales,
        "guests": {
            "total": guests_total,
            "groups": [{"id": gid, "name": name, "count": int(count or 0)} for gid, name, count in group_rows],
        },
        "attention": {
            "critical_stock": int(critical_stock),
            "dismissal_required": int(pending_dismissals),
            "critical_total": int(critical_stock) + int(pending_dismissals),
        },
        "note": "Гости сейчас пока не берутся из локальной базы как факт присутствия: для этого нужен отдельный read-only источник LANGAME «С активной сессией».",
    }


async def _group_guests(request: Request, group_id: int):
    user, _ = await current_user(request)
    owner_required(user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Guest, GuestGroup)
            .join(GuestGroupMember, GuestGroupMember.guest_id == Guest.id)
            .join(GuestGroup, GuestGroup.id == GuestGroupMember.guest_group_id)
            .where(GuestGroup.id == group_id)
            .order_by(Guest.fio)
            .limit(100)
        )).all()
    return {
        "group": {"id": group_id, "name": rows[0][1].name if rows else "Группа"},
        "items": [{"id": g.id, "langame_guest_id": g.langame_guest_id, "fio": g.fio or "Без имени", "phone": g.phone or ""} for g, _ in rows],
    }


JS = r'''<script>
const legacyCurrentSummaryHome=home;
const currentEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const currentFmtMoney=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const currentFmtDuration=m=>{const h=Math.floor(Number(m||0)/60),mm=Number(m||0)%60;return h?`${h} ч ${mm} мин`:`${mm} мин`};
async function currentGroupGuests(id){clear();setBottom(false);back();const d=await api(`/api/current-summary/guests?group_id=${Number(id)}`);const items=d.items||[];root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>${currentEsc(d.group.name)}</h2><span>${items.length}</span></div>${items.length?items.map(g=>`<section class="card"><div class="admin-name">${currentEsc(g.fio)}</div><div class="admin-meta">LANGAME #${currentEsc(g.langame_guest_id)}${g.phone?' · '+currentEsc(g.phone):''}</div></section>`).join(''):'<div class="empty">Гостей в этой группе нет</div>'}`)}
async function home(){if(me?.role!=='owner')return legacyCurrentSummaryHome();clear();setBottom(true);const d=await api('/api/current-summary');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shiftHtml=d.shifts.length?d.shifts.map(s=>`<div class="row"><div class="row-main"><div class="row-title">🟢 ${currentEsc(s.employee)}</div><div class="row-sub">На смене ${currentFmtDuration(s.duration_minutes)} · с ${new Date(s.started_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</div></div><div class="row-value">${currentFmtMoney(s.sales)}</div></div>`).join(''):'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.guests.groups||[]).slice(0,6).map(g=>`<button class="nav-btn" onclick="currentGroupGuests(${Number(g.id)})"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">${currentEsc(g.name)}</span><span class="nav-hint">${g.count} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');const attention=d.attention.critical_total;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Смены, выручка, гости, отчёты и проблемы. Обновлено ${new Date(d.updated_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><section class="card">${shiftHtml}</section><div class="grid"><section class="card"><div class="section-title"><h2>Выручка сегодня</h2></div>${row('Бар и снеки',currentFmtMoney(d.sales.bar))}${row('Игровое время',currentFmtMoney(d.sales.gaming))}${d.sales.other?row('Прочее',currentFmtMoney(d.sales.other)):''}<div class="row"><div class="row-main"><div class="row-title">Всего</div></div><div class="row-value">${currentFmtMoney(d.sales.bar+d.sales.gaming+d.sales.other)}</div></div></section><section class="card"><div class="section-title"><h2>Гости</h2><span>${d.guests.total}</span></div><div class="kpi-value">${d.guests.total}</div><div class="row-sub">Локальная база; не считать это текущим присутствием</div></section></div><div class="section-title"><h2>Группы лояльности</h2><span>открыть список</span></div><div class="nav-card">${groups||'<div class="empty">Группы пока не синхронизированы</div>'}</div><div class="section-title"><h2>Смены и отчёты</h2><span>сегодня</span></div><section class="card">${row('Отчёты сданы',d.reports.submitted)}${row('Ожидают отчёта',d.reports.pending)}${row('Без отчёта / открытая смена',d.reports.open_without_report)}</section><div class="section-title"><h2>Требует внимания</h2><span>${attention}</span></div><section class="card">${row('Критические остатки',d.attention.critical_stock)}${row('Требуется решение по нарушениям',d.attention.dismissal_required)}${row('Критические позиции / проблемы',attention)}</section>`}
</script>'''


async def _index():
    from app.webapp.admin_shift_control import _index as legacy_index
    response = await legacy_index()
    html = response.body.decode("utf-8")
    marker = "document.getElementById('refresh').onclick=home;"
    # Both feature modules inject into the existing page script. The legacy
    # admin module still has an old <script> wrapper, so normalize that wrapper
    # here before adding the current-summary code; otherwise Telegram's HTML
    # parser renders the JavaScript source as page text.
    html = html.replace("<script>\nasync function admins()", "\nasync function admins()", 1)
    html = html.replace("</script>" + marker, marker, 1)
    current_js = JS[len("<script>"):-len("</script>")]
    return HTMLResponse(html.replace(marker, current_js + marker, 1))


def install(web_app):
    web_app.add_api_route("/api/current-summary", _current_summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/current-summary/guests", _group_guests, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    web_app.routes.sort(key=lambda route: 0 if isinstance(route, APIRoute) and route.path in {"/", "/api/current-summary", "/api/current-summary/guests"} and getattr(route.endpoint, "__name__", "") in {"_index", "_current_summary", "_group_guests"} else 1)
