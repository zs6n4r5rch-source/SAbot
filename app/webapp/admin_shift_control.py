from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, Shift, ShiftCloseReport, TelegramUser
from app.webapp.app import current_user, owner_required, dec, iso


async def _admins(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        employees = (await session.execute(select(Employee, TelegramUser).outerjoin(TelegramUser, TelegramUser.employee_id == Employee.id).where(Employee.active.is_(True)).order_by(Employee.full_name))).all()
        shifts = (await session.execute(select(Shift, ShiftCloseReport).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.started_at >= day_start).order_by(Shift.started_at.desc()))).all()
    latest = {}
    submitted = 0
    pending = 0
    for shift, report in shifts:
        if report and report.status == "submitted":
            submitted += 1
        elif shift.ended_at is not None:
            pending += 1
        if shift.employee_id and shift.employee_id not in latest:
            latest[shift.employee_id] = {"shift_id": shift.id, "langame_shift_id": shift.langame_shift_id, "started_at": iso(shift.started_at), "ended_at": iso(shift.ended_at), "status": "open" if shift.ended_at is None else "closed", "cash_sales": dec(shift.cash_sales), "card_sales": dec(shift.card_sales), "mobile_sales": dec(shift.mobile_sales), "sales": dec(shift.cash_sales) + dec(shift.card_sales) + dec(shift.mobile_sales), "refunds": dec(shift.refunds_cash) + dec(shift.refunds_card), "collection": dec(shift.collection), "cash_difference": dec(shift.cash_difference) if shift.cash_difference is not None else None, "report_id": report.id if report else None, "report_status": report.status if report else "missing", "report_submitted_at": iso(report.submitted_at) if report else None, "stock_discrepancies_count": (report.stock_discrepancies_count or 0) if report else None}
    items = [{"id": e.id, "name": e.full_name or f"Сотрудник #{e.id}", "phone": e.phone, "telegram_id": tg.telegram_id if tg else None, "role": tg.role if tg else "not_linked", "access_active": bool(tg and tg.active), "langame_user_id": e.langame_user_id, "shift": latest.get(e.id)} for e, tg in employees]
    return {"items": items, "today": {"date": day_start.date().isoformat(), "reports_submitted": submitted, "reports_pending": pending}}


async def _admin_shifts(request: Request, employee_id: int, days: int = 30):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 90)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise HTTPException(404, "Employee not found")
        rows = (await session.execute(select(Shift, ShiftCloseReport).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(Shift.employee_id == employee_id, Shift.started_at >= start).order_by(Shift.started_at.desc()).limit(200))).all()
    return {"employee": {"id": employee.id, "name": employee.full_name or f"Сотрудник #{employee.id}"}, "days": days, "items": [{"id": shift.id, "langame_shift_id": shift.langame_shift_id, "started_at": iso(shift.started_at), "ended_at": iso(shift.ended_at), "status": "open" if shift.ended_at is None else "closed", "sales": dec(shift.cash_sales) + dec(shift.card_sales) + dec(shift.mobile_sales), "cash_sales": dec(shift.cash_sales), "card_sales": dec(shift.card_sales), "mobile_sales": dec(shift.mobile_sales), "refunds": dec(shift.refunds_cash) + dec(shift.refunds_card), "collection": dec(shift.collection), "cash_difference": dec(shift.cash_difference) if shift.cash_difference is not None else None, "handover_note": shift.handover_note, "report_id": report.id if report else None, "report_status": report.status if report else "missing", "report_submitted_at": iso(report.submitted_at) if report else None, "stock_items_count": report.stock_items_count if report else None, "stock_discrepancies_count": report.stock_discrepancies_count if report else None, "cash_shortage_reason": report.cash_shortage_reason if report else None, "cash_comment": report.cash_comment if report else None, "cleaning_confirmed_at": iso(report.cleaning_confirmed_at) if report else None} for shift, report in rows]}


JS = r'''async function admins(){clear();setBottom(false);back();const d=await api('/api/admins');const items=d.items||[];const active=items.filter(x=>x.shift?.status==='open').length;const submitted=d.today?.reports_submitted||0;const pending=d.today?.reports_pending||0;const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const html=items.length?items.map(x=>{const s=x.shift;let state='⚪ Сегодня смены нет',badge=`<span class="badge ${x.access_active?'good':'warn'}">${x.access_active?'Доступ':'Нет доступа'}</span>`;if(s?.status==='open'){state='🟢 Сейчас на смене';badge='<span class="badge good">На смене</span>'}else if(s?.status==='closed'&&s.report_status==='submitted'){state='⚪ Смена закрыта';badge='<span class="badge good">Отчёт сдан</span>'}else if(s?.status==='closed'){state='🟠 Отчёт не сдан';badge='<span class="badge warn">Отчёт</span>'}return `<section class="card admin-card"><div class="admin-head"><div><div class="admin-name">${esc(x.name)}</div><div class="admin-meta">${state} · ${x.telegram_id?'Telegram привязан':'Telegram не привязан'}</div></div>${badge}</div>${s?`<div class="admin-main"><div class="mini"><div class="mini-label">Смена</div><div class="mini-value">${s.status==='open'?'Открыта':'Закрыта'}</div></div><div class="mini"><div class="mini-label">Продажи</div><div class="mini-value">${money(s.sales)}</div></div><div class="mini"><div class="mini-label">Отчёт</div><div class="mini-value">${s.report_status==='submitted'?'Сдан':'Не сдан'}</div></div><div class="mini"><div class="mini-label">Касса</div><div class="mini-value">${s.cash_difference===null?'—':money(s.cash_difference)}</div></div></div>`:`<div class="admin-main"><div class="mini"><div class="mini-label">Telegram</div><div class="mini-value">${x.telegram_id?'Есть':'Нет'}</div></div><div class="mini"><div class="mini-label">Langame</div><div class="mini-value">${x.langame_user_id||'—'}</div></div>`}<button class="secondary" style="margin-top:10px" onclick="adminDetail(${Number(x.id)})">Открыть смены и отчёты →</button></section>`}).join(''):'<div class="empty">Администраторов пока нет</div>';root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Администраторы</h2><span>${items.length}</span></div><div class="kpis"><div class="kpi"><div class="kpi-label">Сейчас на смене</div><div class="kpi-value good">${active}</div></div><div class="kpi"><div class="kpi-label">Отчётов сдано сегодня</div><div class="kpi-value">${submitted}</div></div><div class="kpi"><div class="kpi-label">Отчётов требуют внимания</div><div class="kpi-value ${pending?'warn':''}">${pending}</div></div><div class="kpi"><div class="kpi-label">Всего администраторов</div><div class="kpi-value">${items.length}</div></div></div>${html}`)}
async function adminDetail(id){clear();setBottom(false);back();const d=await api(`/api/admins/${Number(id)}/shifts?days=30`);const items=d.items||[];const fmt=v=>v?new Date(v).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';const report=s=>s.report_status==='submitted'?'<span class="badge good">Отчёт сдан</span>':s.report_status==='missing'?'<span class="badge warn">Отчёта нет</span>':'<span class="badge warn">Отчёт не завершён</span>';const html=items.length?items.map(s=>`<section class="card"><div class="admin-head"><div><div class="admin-name">${fmt(s.started_at)} · смена #${esc(s.langame_shift_id)}</div><div class="admin-meta">${s.status==='open'?'🟢 Открыта':'⚪ Закрыта'}${s.ended_at?' · '+fmt(s.ended_at):''}</div></div>${report(s)}</div><div class="admin-main"><div class="mini"><div class="mini-label">Продажи</div><div class="mini-value">${money(s.sales)}</div></div><div class="mini"><div class="mini-label">Наличные</div><div class="mini-value">${money(s.cash_sales)}</div></div><div class="mini"><div class="mini-label">Карта</div><div class="mini-value">${money(s.card_sales)}</div></div><div class="mini"><div class="mini-label">Онлайн</div><div class="mini-value">${money(s.mobile_sales)}</div></div></div><div class="row"><div class="row-main"><div class="row-title">Расхождение кассы</div></div><div class="row-value">${s.cash_difference===null?'—':money(s.cash_difference)}</div></div><div class="row"><div class="row-main"><div class="row-title">Товары в отчёте</div><div class="row-sub">Расхождения по остаткам</div></div><div class="row-value">${s.stock_items_count??'—'} / ${s.stock_discrepancies_count??0}</div></div>${s.report_id?`<button class="primary" onclick="shiftReportOpen(${Number(s.report_id)})">📋 Открыть отчёт</button>`:''}</section>`).join(''):'<div class="empty">За последние 30 дней смен не найдено</div>';root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>${esc(d.employee.name)}</h2><span>30 дней</span></div>${html}`)}'''


async def _index():
    path = Path(__file__).resolve().parent / "static" / "index.html"
    html = path.read_text(encoding="utf-8")
    marker = "document.getElementById('refresh').onclick=home;"
    return HTMLResponse(html.replace(marker, JS + marker, 1))


def install(web_app):
    web_app.add_api_route("/api/admins", _admins, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/admins/{employee_id}/shifts", _admin_shifts, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    web_app.routes.sort(key=lambda route: 0 if isinstance(route, APIRoute) and route.path in {"/", "/api/admins", "/api/admins/{employee_id}/shifts"} and getattr(route.endpoint, "__name__", "") in {"_index", "_admins", "_admin_shifts"} else 1)
