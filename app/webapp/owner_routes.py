from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import OwnerReportSettings, UserRole
from app.webapp.app import app, current_user
from app.webapp.p1_routes import attention_center


class OwnerReportSettingsPayload(BaseModel):
    enabled: bool = True
    timezone: str = Field(default="Europe/Moscow", min_length=1, max_length=64)
    hour: int = Field(default=9, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    include_sales: bool = True
    include_shifts: bool = True
    include_inventory: bool = True
    include_discrepancies: bool = True
    include_salary: bool = True
    include_clients: bool = True
    send_excel: bool = True


def _owner(user):
    if user.role != UserRole.OWNER.value:
        raise HTTPException(403, "OWNER access required")


@app.get("/api/owner/attention")
async def owner_attention(request: Request):
    return await attention_center(request)


@app.put("/api/owner/report-settings")
async def update_owner_report_settings(request: Request, payload: OwnerReportSettingsPayload):
    user, _ = await current_user(request)
    _owner(user)
    try:
        ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(400, "Некорректный часовой пояс")
    async with SessionLocal() as session:
        cfg = await session.scalar(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id == user.telegram_id))
        if cfg is None:
            cfg = OwnerReportSettings(owner_telegram_id=user.telegram_id)
            session.add(cfg)
        cfg.enabled = payload.enabled
        cfg.report_timezone = payload.timezone
        cfg.report_hour = payload.hour
        cfg.report_minute = payload.minute
        cfg.include_sales = payload.include_sales
        cfg.include_shifts = payload.include_shifts
        cfg.include_inventory = payload.include_inventory
        cfg.include_discrepancies = payload.include_discrepancies
        cfg.include_salary = payload.include_salary
        cfg.include_clients = payload.include_clients
        cfg.send_excel = payload.send_excel
        await session.commit()
        return {"ok": True, "configured": True, "enabled": cfg.enabled, "timezone": cfg.report_timezone, "hour": cfg.report_hour, "minute": cfg.report_minute, "include_sales": cfg.include_sales, "include_shifts": cfg.include_shifts, "include_inventory": cfg.include_inventory, "include_discrepancies": cfg.include_discrepancies, "include_salary": cfg.include_salary, "include_clients": cfg.include_clients, "send_excel": cfg.send_excel}


@app.middleware("http")
async def owner_ux(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/" or not isinstance(response, HTMLResponse):
        return response
    body = getattr(response, "body", None)
    if not body:
        return response
    html = body.decode("utf-8")
    injection = r'''<script>
(function(){
  window.attention=async function(){
    clear();setBottom(false);back();
    try{
      const d=await api('/api/owner/attention');
      const items=(d.items||[]).map(x=>{
        let action='';
        if(x.type==='critical_stock') action='<button class="secondary" style="margin-top:8px" onclick="inventory()">Открыть остатки</button>';
        if(x.type==='shift_report'||x.type==='cash_issue') action='<button class="secondary" style="margin-top:8px" onclick="ownerShifts()">Открыть контроль смен</button>';
        if(x.type==='dismissal_required') action='<button class="secondary" style="margin-top:8px" onclick="penalties()">Открыть нарушения</button>';
        return `<div class="card"><div class="row"><div class="row-main"><div class="row-title">${x.title||'Требует внимания'}</div><div class="row-sub">${x.employee||x.product||''}${x.amount!=null?' · '+money(x.amount):''}</div></div><div class="badge warn">Действие</div></div>${action}</div>`;
      }).join('');
      root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Центр внимания</h2><span>${d.count||0}</span></div><p class="muted">Сюда попадают только исключения, по которым владельцу нужно принять решение или проверить результат.</p>${items||'<div class="empty">Критических вопросов нет.</div>'}`);
    }catch(e){fail(e)}
  };
  window.settings=async function(){
    clear();setBottom(false);back();
    try{
      const d=await api('/api/settings');
      const cfg={enabled:d.enabled!==false,timezone:d.timezone||'Europe/Moscow',hour:Number(d.hour||9),minute:Number(d.minute||0),include_sales:d.include_sales!==false,include_shifts:d.include_shifts!==false,include_inventory:d.include_inventory!==false,include_discrepancies:d.include_discrepancies!==false,include_salary:d.include_salary!==false,include_clients:d.include_clients!==false,send_excel:d.send_excel!==false};
      root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Настройки ежедневного отчёта</h2><span>${cfg.enabled?'Включён':'Выключен'}</span></div><section class="card"><label>Часовой пояс</label><input id="or-tz" value="${cfg.timezone}"><label>Час</label><input id="or-hour" type="number" min="0" max="23" value="${cfg.hour}"><label>Минута</label><input id="or-minute" type="number" min="0" max="59" value="${cfg.minute}"><label><input id="or-enabled" type="checkbox" ${cfg.enabled?'checked':''}> Включать ежедневный отчёт</label><label><input id="or-sales" type="checkbox" ${cfg.include_sales?'checked':''}> Продажи</label><label><input id="or-shifts" type="checkbox" ${cfg.include_shifts?'checked':''}> Смены</label><label><input id="or-inventory" type="checkbox" ${cfg.include_inventory?'checked':''}> Остатки</label><label><input id="or-disc" type="checkbox" ${cfg.include_discrepancies?'checked':''}> Расхождения</label><label><input id="or-salary" type="checkbox" ${cfg.include_salary?'checked':''}> Зарплата</label><label><input id="or-clients" type="checkbox" ${cfg.include_clients?'checked':''}> Клиенты</label><label><input id="or-excel" type="checkbox" ${cfg.send_excel?'checked':''}> Excel</label><button class="primary" id="or-save">Сохранить</button></section>`);
      document.getElementById('or-save').onclick=async()=>{try{await api('/api/owner/report-settings',{method:'PUT',body:JSON.stringify({enabled:orEnabled.checked,timezone:orTz.value.trim(),hour:Number(orHour.value),minute:Number(orMinute.value),include_sales:orSales.checked,include_shifts:orShifts.checked,include_inventory:orInventory.checked,include_discrepancies:orDisc.checked,include_salary:orSalary.checked,include_clients:orClients.checked,send_excel:orExcel.checked})});alert('Настройки сохранены')}catch(e){fail(e)}};
    }catch(e){fail(e)}
  };
})();
</script>'''
    html = html.replace("</body>", injection + "</body>")
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return HTMLResponse(content=html, status_code=response.status_code, headers=headers, media_type="text/html")
