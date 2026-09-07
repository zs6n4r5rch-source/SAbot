from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, SalaryViolation, Shift, ShiftCloseReport
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user, owner_required, dec
from app.webapp.management_dashboard import _sales, _guest_groups, _guest_group_count
from app.webapp.management_dashboard import _index as management_index

MSK = ZoneInfo("Europe/Moscow")


async def _summary(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        open_rows = (await session.execute(select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        reports = (await session.execute(select(ShiftCloseReport, Shift, Employee).join(Shift, Shift.id == ShiftCloseReport.shift_id).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.started_at >= start))).all()
        critical = await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)) or 0
        dismissals = await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0
    sales = await _sales(start, now)
    groups = []
    try:
        for g in await _guest_groups():
            groups.append({**g, "count": await _guest_group_count(g["id"])})
    except LangameAPIError:
        groups = []
    return {
        "updated_at": now.astimezone(MSK).isoformat(),
        "shifts": [{"id": s.id, "employee": e.full_name if e else f"Администратор #{s.employee_id}", "started_at": s.started_at.astimezone(MSK).isoformat(), "sales": dec(s.cash_sales)+dec(s.card_sales)+dec(s.mobile_sales)} for s,e in open_rows],
        "reports": {"submitted": sum(1 for r,_,_ in reports if r.status == "submitted"), "pending": sum(1 for r,s,_ in reports if r.status != "submitted" and s.ended_at is not None), "open_without_report": sum(1 for r,s,_ in reports if r.status != "submitted" and s.ended_at is None)},
        "sales": {"bar": sales["bar"], "gaming": sales["gaming"], "total": sales["total"]},
        "guests": {"active": None, "today": None, "note": "Активные сессии и точный список гостей за сутки требуют подтверждённого read-only endpoint LANGAME; текущий клиент его не предоставляет."},
        "groups": groups,
        "attention": {"critical_stock": int(critical), "dismissal_required": int(dismissals), "critical_total": int(critical)+int(dismissals)},
    }


JS = r'''<script>
async function home(){if(me?.role!=='owner'){return legacyCurrentSummaryHome?.()};clear();setBottom(true);const d=await api('/api/current-summary-v2');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn" onclick="adminShiftOpen(${s.id})"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${mgEsc(s.employee)}</span><span class="nav-hint">С ${new Date(s.started_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</span></span><span class="nav-arrow">${mgMoney(s.sales)}</span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${g.id})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${mgEsc(g.name)}</span><span class="nav-hint">${g.count} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${new Date(d.updated_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="grid"><section class="card"><div class="section-title"><h2>Выручка сегодня</h2></div>${row('Бар и снеки',mgMoney(d.sales.bar))}${row('Игровое время',mgMoney(d.sales.gaming))}${row('Всего',mgMoney(d.sales.total))}</section><section class="card"><div class="section-title"><h2>Гости сейчас</h2><span>LANGAME</span></div><div class="kpi-value">${d.guests.active??'—'}</div><div class="row-sub">С активной сессией</div></section></div><div class="section-title"><h2>Гости за сегодня</h2><span>LANGAME</span></div><section class="card"><div class="kpi-value">${d.guests.today??'—'}</div><div class="row-sub">Точный показатель будет подключён после подтверждения read-only endpoint LANGAME.</div></section><div class="section-title"><h2>Группы лояльности</h2><span>LANGAME</span></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Смены и отчёты</h2><span>открыть</span></div><div class="nav-card">${iconNav('✓','Отчёты сданы',String(d.reports.submitted),()=>adminReports('submitted')).outerHTML}${iconNav('⌛','Ожидают отчёта',String(d.reports.pending),()=>adminReports('pending')).outerHTML}${iconNav('🟢','Открытые смены без отчёта',String(d.reports.open_without_report),()=>adminReports('open')).outerHTML}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${iconNav('📦','Критические остатки',String(d.attention.critical_stock),()=>inventory()).outerHTML}${iconNav('⚠️','Требуется решение',String(d.attention.dismissal_required),()=>attention()).outerHTML}</div>`}
async function adminShiftOpen(id){clear();setBottom(false);back();const d=await api('/api/admins');const a=(d.items||[]).find(x=>x.id===id);root.insertAdjacentHTML('beforeend',`<section class="hero"><div class="eyebrow">СМЕНА</div><div class="hero-title">${mgEsc(a?.name||'Администратор')}</div><div class="hero-sub">Открытая смена. Детали и закрытие доступны в разделе администраторов.</div></section><button class="primary" onclick="admins()">Открыть администратора</button>`)}
function adminReports(kind){admins();}
</script>'''


async def _index():
    response = await management_index()
    html = response.body.decode("utf-8")
    return HTMLResponse(html.replace("</body>", JS + "</body>", 1))


def install(web_app):
    web_app.add_api_route("/api/current-summary-v2", _summary, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == "/" and route.endpoint is _index:
            web_app.routes.remove(route)
            web_app.routes.insert(0, route)
            break
