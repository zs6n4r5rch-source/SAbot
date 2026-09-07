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
    user,_=await current_user(request); owner_required(user); now=datetime.now(timezone.utc); day_start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    async with SessionLocal() as session:
        employees=(await session.execute(select(Employee,TelegramUser).outerjoin(TelegramUser,TelegramUser.employee_id==Employee.id).where(Employee.active.is_(True)).order_by(Employee.full_name))).all()
        shifts=(await session.execute(select(Shift,ShiftCloseReport).outerjoin(ShiftCloseReport,ShiftCloseReport.shift_id==Shift.id).where(Shift.started_at>=day_start).order_by(Shift.started_at.desc()))).all()
    latest={}; submitted=pending=0
    for shift,report in shifts:
        if report and report.status=='submitted': submitted+=1
        elif shift.ended_at is not None: pending+=1
        if shift.employee_id and shift.employee_id not in latest:
            latest[shift.employee_id]={"shift_id":shift.id,"langame_shift_id":shift.langame_shift_id,"started_at":iso(shift.started_at),"ended_at":iso(shift.ended_at),"status":"open" if shift.ended_at is None else "closed","sales":dec(shift.cash_sales)+dec(shift.card_sales)+dec(shift.mobile_sales),"cash_difference":dec(shift.cash_difference) if shift.cash_difference is not None else None,"report_id":report.id if report else None,"report_status":report.status if report else "missing"}
    return {"items":[{"id":e.id,"name":e.full_name or f"Сотрудник #{e.id}","phone":e.phone,"telegram_id":tg.telegram_id if tg else None,"role":tg.role if tg else "not_linked","access_active":bool(tg and tg.active),"langame_user_id":e.langame_user_id,"shift":latest.get(e.id)} for e,tg in employees],"today":{"date":day_start.date().isoformat(),"reports_submitted":submitted,"reports_pending":pending}}

async def _admin_shifts(request: Request, employee_id: int, days: int = 30):
    user,_=await current_user(request); owner_required(user); days=min(max(days,1),90); start=datetime.now(timezone.utc)-timedelta(days=days)
    async with SessionLocal() as session:
        employee=await session.get(Employee,employee_id)
        if not employee: raise HTTPException(404,'Employee not found')
        rows=(await session.execute(select(Shift,ShiftCloseReport).outerjoin(ShiftCloseReport,ShiftCloseReport.shift_id==Shift.id).where(Shift.employee_id==employee_id,Shift.started_at>=start).order_by(Shift.started_at.desc()).limit(200))).all()
    return {"employee":{"id":employee.id,"name":employee.full_name or f"Сотрудник #{employee.id}"},"days":days,"items":[{"id":s.id,"langame_shift_id":s.langame_shift_id,"started_at":iso(s.started_at),"ended_at":iso(s.ended_at),"status":"open" if s.ended_at is None else "closed","sales":dec(s.cash_sales)+dec(s.card_sales)+dec(s.mobile_sales),"cash_sales":dec(s.cash_sales),"card_sales":dec(s.card_sales),"mobile_sales":dec(s.mobile_sales),"cash_difference":dec(s.cash_difference) if s.cash_difference is not None else None,"report_id":r.id if r else None,"report_status":r.status if r else "missing","stock_items_count":r.stock_items_count if r else None,"stock_discrepancies_count":r.stock_discrepancies_count if r else None} for s,r in rows]}

JS=r'''<script>
window.saAdminDetail=async function(id){clear();setBottom(false);back();try{const d=await api(`/api/admins/${Number(id)}/shifts?days=30`);const fmt=v=>v?new Date(v).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>${d.employee.name}</h2><span>30 дней</span></div>`+(d.items||[]).map(s=>`<section class="card">${row('Смена',s.status==='open'?'Открыта':'Закрыта',fmt(s.started_at)+' → '+fmt(s.ended_at))}${row('Продажи',money(s.sales))}${row('Наличные',money(s.cash_sales))}${row('Карта',money(s.card_sales))}${row('Онлайн',money(s.mobile_sales))}${row('Разница кассы',s.cash_difference==null?'—':money(s.cash_difference))}${s.report_id?`<button class="primary" onclick="shiftReportOpen(${Number(s.report_id)})">📋 Открыть отчёт</button>`:''}</section>`).join('')||'<div class="empty">Смен нет</div>')}catch(e){fail(e)}};
window.saAdmins=async function(){clear();setBottom(false);back();try{const d=await api('/api/admins');const items=d.items||[];root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Администраторы</h2><span>${items.length}</span></div>`+(items.map(x=>`<button class="nav-btn" style="background:var(--sa-surface);margin:5px 0" onclick="saAdminDetail(${Number(x.id)})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">${x.name}</span><span class="nav-hint">${x.shift?.status==='open'?'🟢 Сейчас на смене':x.shift?.status==='closed'?(x.shift.report_status==='submitted'?'⚪ Смена закрыта':'🟠 Отчёт не сдан'):'⚪ Сегодня смены нет'}</span></span><span class="nav-arrow">›</span></button>`).join(''))}`)}catch(e){fail(e)}};
window.admins=window.saAdmins;
</script>'''

async def _index():
    path=Path(__file__).resolve().parent/'static'/'index.html'; html=path.read_text(encoding='utf-8'); marker="document.getElementById('refresh').onclick=home;"; return HTMLResponse(html.replace(marker,JS+marker,1))

def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route,APIRoute) and route.path in ('/api/admins','/api/admins/{employee_id}/shifts'): web_app.routes.remove(route)
    web_app.add_api_route('/api/admins/{employee_id}/shifts',_admin_shifts,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/api/admins',_admins,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/',_index,methods=['GET'],include_in_schema=False)
