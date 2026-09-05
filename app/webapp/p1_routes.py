from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, SalaryViolation, Shift, ShiftCloseReport, UserRole
from app.webapp.app import app, current_user, iso, dec


def _owner(user):
    if user.role != UserRole.OWNER.value:
        raise HTTPException(403, "OWNER access required")


@app.get("/api/attention-center")
async def attention_center(request: Request):
    user, _ = await current_user(request)
    _owner(user)
    async with SessionLocal() as session:
        critical = (await session.execute(select(InventoryBalance.id).where(
            InventoryBalance.min_stock > 0,
            InventoryBalance.quantity <= InventoryBalance.min_stock,
        ))).scalars().all()
        dismissal = (await session.execute(select(SalaryViolation, Employee).join(
            Employee, Employee.id == SalaryViolation.employee_id
        ).where(SalaryViolation.dismissal_required.is_(True)).order_by(
            SalaryViolation.created_at.desc()
        ))).all()
        open_shifts = (await session.execute(select(Shift).where(Shift.ended_at.is_(None)))).scalars().all()
        closed_shifts = (await session.execute(select(Shift, Employee).outerjoin(
            Employee, Employee.id == Shift.employee_id
        ).where(Shift.status == "closed").order_by(Shift.started_at.desc()).limit(200))).all()
        shift_ids = [s.id for s, _ in closed_shifts]
        reports = (await session.execute(select(ShiftCloseReport).where(
            ShiftCloseReport.shift_id.in_(shift_ids)
        ))).scalars().all() if shift_ids else []
        report_map = {r.shift_id: r for r in reports}
        awaiting = [(s, e) for s, e in closed_shifts if report_map.get(s.id) is None or report_map[s.id].status != "submitted"]
        cash_issues = [(s, e, report_map[s.id]) for s, e in closed_shifts if s.id in report_map and report_map[s.id].status == "submitted" and report_map[s.id].cash_difference is not None and dec(report_map[s.id].cash_difference) < 0]
        return {
            "count": len(critical) + len(dismissal) + len(awaiting) + len(cash_issues),
            "critical_stock": len(critical),
            "dismissal_required": len(dismissal),
            "awaiting_shift_reports": len(awaiting),
            "cash_issues": len(cash_issues),
            "open_shifts": len(open_shifts),
            "items": [
                *[{"type": "dismissal_required", "title": "Требуется решение по нарушению", "employee": e.full_name, "violation_id": v.id, "amount": dec(v.amount), "created_at": iso(v.created_at)} for v, e in dismissal[:20]],
                *[{"type": "shift_report", "title": "Смена ждёт закрывающего отчёта", "employee": e.full_name if e else str(s.employee_id), "shift_id": s.id, "started_at": iso(s.started_at), "ended_at": iso(s.ended_at)} for s, e in awaiting[:20]],
                *[{"type": "cash_issue", "title": "Отрицательная разница по кассе", "employee": e.full_name if e else str(s.employee_id), "shift_id": s.id, "amount": dec(r.cash_difference)} for s, e, r in cash_issues[:20]],
                *[{"type": "critical_stock", "title": "Критический остаток", "inventory_id": i} for i in critical[:20]],
            ],
        }


@app.get("/api/owner-shifts")
async def owner_shifts(request: Request, days: int = 30):
    user, _ = await current_user(request)
    _owner(user)
    days = min(max(days, 1), 90)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Shift, Employee, ShiftCloseReport).outerjoin(
            Employee, Employee.id == Shift.employee_id
        ).outerjoin(ShiftCloseReport, ShiftCloseReport.shift_id == Shift.id).where(
            Shift.started_at >= start
        ).order_by(Shift.started_at.desc()).limit(200))).all()
        result = []
        for shift, employee, report in rows:
            end = shift.ended_at or now
            duration_minutes = max(0, int((end - shift.started_at).total_seconds() // 60)) if shift.started_at else 0
            result.append({
                "id": shift.id,
                "langame_shift_id": shift.langame_shift_id,
                "employee": employee.full_name if employee else str(shift.employee_id),
                "started_at": iso(shift.started_at),
                "ended_at": iso(shift.ended_at),
                "duration_minutes": duration_minutes,
                "status": "open" if shift.ended_at is None else "closed",
                "report_status": report.status if report else None,
                "cash_difference": dec(report.cash_difference) if report else None,
            })
        return {"days": days, "items": result}


@app.middleware("http")
async def p1_p2_ux(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/" or not isinstance(response, HTMLResponse):
        return response
    body = getattr(response, "body", None)
    if not body:
        return response
    html = body.decode("utf-8")
    html = html.replace("Штрафы · 30 дней", "Нарушения · 30 дней")
    html = html.replace("'Штрафы'", "'Нарушения'")
    html = html.replace('>Штрафы<', '>Нарушения<')
    injection = r'''<script>
(function(){
  const originalHome=window.home;
  if(typeof originalHome!=='function') return;
  window.ownerShifts=async function(){
    clear();setBottom(false);back();
    try{
      const d=await api('/api/owner-shifts');
      const body=d.items.length?d.items.map(x=>{const h=Math.floor(x.duration_minutes/60),m=x.duration_minutes%60;const state=x.status==='open'?'В работе':(x.report_status==='submitted'?'Закрыт':'Ждёт отчёт');return `<div class="row"><div class="row-main"><div class="row-title">${x.employee||'Администратор'}</div><div class="row-sub">${x.started_at||''} → ${x.ended_at||'сейчас'} · ${h}ч ${m}м</div></div><div class="row-value">${state}</div></div>`}).join(''):'<div class="empty">Смен за период нет.</div>';
      root.insertAdjacentHTML('beforeend',card('Контроль смен',body));
    }catch(e){fail(e)}
  };
  window.home=async function(){
    await originalHome();
    document.querySelectorAll('#root .section-title,#root .nav-card').forEach(x=>x.remove());
    try{
      const who=await api('/api/me');
      if(who.role==='owner'){
        const d=await api('/api/attention-center');
        const count=Number(d.count||0);
        const label=count?`Требует внимания · ${count}`:'Требует внимания';
        const box=document.createElement('section');box.className='card';
        box.innerHTML=`<div class="section-title"><h2>🔴 ${label}</h2><span>центр действий</span></div><p class="muted">Нарушения, незакрытые отчёты, кассовые расхождения и критические остатки.</p><button class="primary" id="attention-home-btn">Открыть центр внимания</button><button class="secondary" id="owner-shifts-home-btn" style="margin-top:8px">Контроль смен</button>`;
        root.appendChild(box);
        document.getElementById('attention-home-btn').onclick=attention;
        document.getElementById('owner-shifts-home-btn').onclick=ownerShifts;
      }else{
        const sh=await api('/api/my-shift');
        const state=sh.state==='open'?'Смена в работе':sh.state==='awaiting_report'?'Смена ждёт закрывающий отчёт':sh.state==='closed'?'Смена закрыта':'Смена не найдена';
        const salary=await api('/api/my-salary/current');
        const box=document.createElement('section');box.className='card';
        box.innerHTML=`<div class="section-title"><h2>Моё состояние</h2><span>${state}</span></div><div class="row"><div class="row-main"><div class="row-title">Смена</div><div class="row-sub">${sh.started_at||'—'} → ${sh.ended_at||'сейчас'}</div></div><div class="row-value">${state}</div></div><div class="row"><div class="row-main"><div class="row-title">Зарплата за текущий период</div><div class="row-sub">Период ${salary.from} — ${salary.to}</div></div><div class="row-value">${money(salary.total)}</div></div><button class="primary" id="shift-home-btn">${sh.state==='open'?'Открыть смену':sh.state==='awaiting_report'?'Закрыть смену':'Посмотреть результат'}</button>`;
        root.appendChild(box);
        document.getElementById('shift-home-btn').onclick=sh.state==='awaiting_report'||sh.state==='open'?closeShift:shiftResult;
      }
    }catch(e){fail(e)}
  };
})();
</script>'''
    html = html.replace("</body>", injection + "</body>")
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return HTMLResponse(content=html, status_code=response.status_code, headers=headers, media_type="text/html")
