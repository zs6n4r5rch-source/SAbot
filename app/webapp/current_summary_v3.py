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
    if isinstance(payload, list): return payload
    if not isinstance(payload, dict): return []
    for key in ("items","data","results","rows"):
        value=payload.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict):
            nested=_rows(value)
            if nested: return nested
    return []

def _wall(value):
    if not value: return None
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).isoformat()

def _money(v):
    try: return float(v or 0)
    except (TypeError,ValueError): return 0.0

def _active(row):
    try: return int(row.get("normal_stop",1) or 0)==0
    except (TypeError,ValueError): return str(row.get("normal_stop")).lower() in {"false","0","no"}

async def _pages(method,*args,**kwargs):
    rows=[]
    for page in range(1,51):
        payload=await method(*args,page=page,page_limit=500,**kwargs)
        batch=[r for r in _rows(payload) if isinstance(r,dict)]
        if not batch: break
        rows.extend(batch)
        p=payload.get("pagination") or {} if isinstance(payload,dict) else {}
        last=payload.get("total_pages") or p.get("total_pages") or p.get("last_page") if isinstance(payload,dict) else None
        if last and page>=int(last): break
    return rows

async def _live(now):
    today=now.astimezone(MSK).date()
    sessions=await _pages(langame_client.guest_sessions,(today-timedelta(days=1)).isoformat(),today.isoformat())
    active=[r for r in sessions if _active(r) and r.get("guest_id") is not None]
    today_rows=[r for r in sessions if r.get("guest_id") is not None and str(r.get("date_start",""))[:10]==today.isoformat()]
    balances=await _pages(langame_client.balances,today.isoformat(),today.isoformat())
    products=await _pages(langame_client.product_sales,today.isoformat(),today.isoformat())
    gaming=sum(max(0,_money(r.get("amount"))) for r in balances)
    bar=sum(max(0,_money(r.get("price_sale"))*_money(r.get("count"))) for r in products if not int(r.get("cancel",0) or 0))
    return len({int(r["guest_id"]) for r in active}),len(active),len({int(r["guest_id"]) for r in today_rows}),gaming,bar

async def _group_guests(group_id):
    rows=[]
    for page in range(1,51):
        payload=await langame_client.guests_search(groups=[int(group_id)],size=100,page=page)
        batch=[r for r in _rows(payload) if isinstance(r,dict)]
        if not batch: break
        rows.extend(batch)
        last=(payload.get("pagination") or {}).get("last_page")
        if last and page>=int(last): break
    return rows

async def _summary(request: Request):
    user,_=await current_user(request); owner_required(user); now=datetime.now(timezone.utc)
    async with SessionLocal() as session:
        opens=(await session.execute(select(Shift,Employee).outerjoin(Employee,Employee.id==Shift.employee_id).where(Shift.ended_at.is_(None)).order_by(Shift.started_at))).all()
        previous=(await session.execute(select(Shift,Employee,ShiftCloseReport).outerjoin(Employee,Employee.id==Shift.employee_id).outerjoin(ShiftCloseReport,ShiftCloseReport.shift_id==Shift.id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
        critical=await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock>0,InventoryBalance.quantity<=InventoryBalance.min_stock)) or 0
        dismissals=await session.scalar(select(func.count(SalaryViolation.id)).where(SalaryViolation.dismissal_required.is_(True))) or 0
    try: active,active_sessions,today_guests,gaming,bar=await _live(now)
    except LangameAPIError: active=active_sessions=today_guests=gaming=bar=None
    groups=[]
    try:
        for g in _rows(await langame_client.guest_groups()):
            if g.get("id") is not None and g.get("name"):
                try:
                    payload = await langame_client.guests_search(groups=[int(g["id"])], size=1, page=1)
                    count = int((payload.get("pagination") or {}).get("total", 0))
                except Exception: count=None
                groups.append({"id":int(g["id"]),"name":str(g["name"]),"count":count})
    except LangameAPIError: pass
    prev=None
    if previous:
        s,e,r=previous; prev={"report_id":r.id if r else None,"employee":e.full_name if e else f"Администратор #{s.employee_id}","started_at":_wall(s.started_at),"ended_at":_wall(s.ended_at),"status":r.status if r else "no_report"}
    total=None if gaming is None or bar is None else gaming+bar
    return {"updated_at":now.astimezone(MSK).isoformat(),"shifts":[{"employee_id":s.employee_id,"employee":e.full_name if e else f"Администратор #{s.employee_id}","started_at":_wall(s.started_at)} for s,e in opens],"previous_report":prev,"sales":{"gaming":gaming,"bar":bar,"total":total},"guests":{"active":active,"active_sessions":active_sessions,"today":today_guests},"groups":groups,"attention":{"critical_stock":int(critical),"dismissal_required":int(dismissals),"critical_total":int(critical)+int(dismissals)}}

async def _group_api(request:Request,group_id:int):
    user,_=await current_user(request); owner_required(user)
    try:
        rows=await _group_guests(group_id)
        return {"items":[{"guest_id":r.get("guest_id",r.get("id")),"fio":r.get("fio") or r.get("name") or r.get("phone") or "Без имени","phone":r.get("phone") or ""} for r in rows if r.get("guest_id",r.get("id")) is not None]}
    except LangameAPIError as exc: raise HTTPException(502,str(exc)) from exc

async def _guest_api(request:Request,guest_id:int):
    user,_=await current_user(request); owner_required(user)
    try:
        rows=_rows(await langame_client.guest_by_id(int(guest_id))); r=rows[0] if rows else {}
        return {"guest_id":int(guest_id),"fio":r.get("fio") or r.get("name") or r.get("phone") or f"Гость #{guest_id}","phone":r.get("phone") or "","balance":r.get("balance"),"bonus_balance":r.get("bonus_balance"),"black_list":r.get("black_list")}
    except LangameAPIError as exc: raise HTTPException(502,str(exc)) from exc

JS=r'''<script>
const svOldHome=window.home;
const svM=v=>v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const svE=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const svT=v=>v?new Date(v).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):'—';
const svR=(a,b)=>`<div class="row"><div class="row-main"><div class="row-title">${svE(a)}</div></div><div class="row-value">${svE(b)}</div></div>`;
function svBack(){root.prepend(btn('← Назад',window.home,'back'))}
async function crmGroup(id){clear();setBottom(false);const d=await api('/api/current-summary-v2/guests?group_id='+id);root.innerHTML=`<section class="hero"><div class="eyebrow">ГОСТИ · ГРУППА</div><div class="hero-title">Группа</div></section><div class="nav-card">${(d.items||[]).map(x=>`<button class="nav-btn" onclick="crmGuestOpen(${Number(x.guest_id)})"><span class="nav-icon">👤</span><span class="nav-copy"><span class="nav-label">${svE(x.fio)}</span><span class="nav-hint">${svE(x.phone)}</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Гости не найдены</div>'}</div>`;svBack()}
async function crmGuestOpen(id){clear();setBottom(false);const d=await api('/api/current-summary-v2/guest/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ГОСТЬ</div><div class="hero-title">${svE(d.fio)}</div><div class="hero-sub">LANGAME #${Number(d.guest_id)}</div></section><section class="card">${svR('Телефон',d.phone||'—')}${svR('Баланс',svM(d.balance))}${svR('Бонусы',svM(d.bonus_balance))}</section>`;svBack()}
async function svReport(id){if(!id)return;clear();setBottom(false);const d=await api('/api/work-center-v3/reports/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ОТЧЁТ О СМЕНЕ</div><div class="hero-title">${svE(d.employee)}</div><div class="hero-sub">${svT(d.started_at)} — ${svT(d.ended_at)}</div></section><section class="card">${svR('Статус',d.status)}${svR('Расчётная наличность',svM(d.cash_expected))}${svR('Фактическая наличность',svM(d.cash_actual))}${svR('Разница кассы',d.cash_difference==null?'—':svM(d.cash_difference))}${svR('Проверено товаров',d.stock_items_count??'—')}${svR('Расхождений',d.stock_discrepancies_count??0)}</section>`;svBack()}
window.home=async function(){if(me?.role!=='owner')return svOldHome?.();clear();setBottom(true);const d=await api('/api/current-summary-v2');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;window.__summaryGroups=d.groups||[];const shifts=(d.shifts||[]).map(s=>`<button class="nav-btn"><span class="nav-icon">🟢</span><span class="nav-copy"><span class="nav-label">${svE(s.employee)}</span><span class="nav-hint">С ${svT(s.started_at)}</span></span></button>`).join('')||'<div class="empty">Сейчас открытых смен нет</div>';const groups=(d.groups||[]).map(g=>`<button class="nav-btn" onclick="crmGroup(${Number(g.id)})"><span class="nav-icon">🏆</span><span class="nav-copy"><span class="nav-label">${svE(g.name)}</span><span class="nav-hint">${g.count==null?'нет данных':g.count+' гостей'}</span></span><span class="nav-arrow">›</span></button>`).join('');const p=d.previous_report;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Обновлено ${svT(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><div class="nav-card">${shifts}</div><div class="section-title"><h2>Выручка сегодня</h2></div><section class="card">${svR('Бар и снеки',svM(d.sales.bar))}${svR('Игровое время',svM(d.sales.gaming))}${svR('Всего',svM(d.sales.total))}</section><div class="section-title"><h2>Гости и лояльность</h2></div><div class="nav-card">${groups||'<div class="empty">Группы LANGAME не найдены</div>'}</div><div class="section-title"><h2>Отчёт предыдущей смены</h2></div><div class="nav-card">${p?`<button class="nav-btn" onclick="svReport(${Number(p.report_id||0)})"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">${svE(p.employee)}</span><span class="nav-hint">${svT(p.started_at)} — ${svT(p.ended_at)}</span></span><span class="nav-arrow">›</span></button>`:'<div class="empty">Предыдущей смены нет</div>'}</div><div class="section-title"><h2>Требует внимания</h2><span>${d.attention.critical_total}</span></div><div class="nav-card">${d.attention.critical_stock?`<button class="nav-btn" onclick="workWarehouse&&workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${d.attention.critical_stock}</span></span><span class="nav-arrow">›</span></button>`:''}${d.attention.dismissal_required?`<button class="nav-btn" onclick="workControl&&workControl()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Требуется решение</span><span class="nav-hint">${d.attention.dismissal_required}</span></span><span class="nav-arrow">›</span></button>`:''}${!d.attention.critical_total?'<div class="empty">Критических вопросов нет</div>':''}</div>`}
</script>'''

async def _index():
    response=await management_index(); html=response.body.decode('utf-8'); return HTMLResponse(html.replace('</body>',JS+'</body>',1))

def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route,APIRoute) and route.path in ('/api/current-summary-v2','/api/current-summary-v2/guests','/api/current-summary-v2/guest/{guest_id}'):
            web_app.routes.remove(route)
    web_app.add_api_route('/api/current-summary-v2',_summary,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/api/current-summary-v2/guests',_group_api,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/api/current-summary-v2/guest/{guest_id}',_guest_api,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/',_index,methods=['GET'],include_in_schema=False)
