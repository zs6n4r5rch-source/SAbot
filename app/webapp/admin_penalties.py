from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from app.db.session import SessionLocal
from app.models import Employee, SalaryViolation
from app.webapp.app import current_user, owner_required, dec, iso


PENALTY_RULES = [
    ("P250-01", "Не указан номер гостя при инкассации денег", 250),
    ("P250-02", "Ошибка в отчёте Telegram или его отсутствие в течение 30 минут (опечатки не считаются)", 250),
    ("P250-03", "Пустые места в холодильнике", 250),
    ("P250-04", "Переполненные мусорные ведра в течение 30 минут", 250),
    ("P250-05", "Спящий гость в течение 30 минут", 250),
    ("P250-06", "Грязь/пыль на столах и рабочем месте администратора/барной стойке, посторонние предметы на столе администратора", 250),
    ("P250-07", "Несвоевременная заявка на замену ламп, туалетной бумаги, клининга и т. д.", 250),
    ("P250-08", "Невыполнение регламента по встрече гостя", 250),
    ("P500-01", "Курение сигарет вне специально отведённых мест", 500),
    ("P500-02", "Нахождение гостя со своими напитками без оплаты пробкового сбора", 500),
    ("P500-03", "Мятая рабочая форма, отсутствие формы, неопрятный внешний вид", 500),
    ("P500-04", "Коробки, ящики, упаковочные материалы и иной мусор на входе/ресепшене", 500),
    ("P500-05", "Нарушение кассовой дисциплины", 500),
    ("P500-06", "Провал тайного покупателя (входящий поток/звонок)", 500),
    ("P500-07", "Пропуск обновления игр", 500),
    ("P500-08", "Нерабочие устройства в течение суток без уведомления в рабочий чат и попытки решить через поддержку", 500),
    ("P500-09", "Алкогольные напитки у гостей", 500),
    ("P500-10", "Мусор на столах гостей", 500),
    ("P500-11", "Не поправленное компьютерное или PS-место в течение 30 минут", 500),
    ("P500-12", "Нет ответа на рабочий телефон", 500),
    ("P500-13", "Оскорбление сотрудников, гостей, поведение, не соответствующее стандартам клуба", 500),
    ("P1000-01", "Присутствие в помещении посторонних лиц в нерабочее время (не клиент)", 1000),
    ("P1000-02", "Перерыв в ведении коммерческой деятельности в рабочие часы (за исключением обеда)", 1000),
    ("P1000-03", "Опоздание на час и более", 1000),
    ("P1000-04", "Сон на смене", 1000),
    ("P1000-05", "Присвоение денежных средств при использовании скидок, некорректным ценником и прочее", 1000),
    ("P2000-01", "Не выход на смену", 2000),
]
RULES = {code: {"code": code, "title": title, "amount": amount} for code, title, amount in PENALTY_RULES}


class PenaltyCreate(BaseModel):
    employee_id: int = Field(gt=0)
    rule_code: str = Field(min_length=1, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)
    shift_id: int | None = Field(default=None, gt=0)


async def penalty_rules(request: Request):
    user, _ = await current_user(request)
    owner_required(user)
    return {"items": list(RULES.values())}


async def employee_penalties(request: Request, employee_id: int, days: int = 365):
    user, _ = await current_user(request)
    owner_required(user)
    days = min(max(days, 1), 3650)
    start = datetime.now(timezone.utc).timestamp() - days * 86400
    start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
    async with SessionLocal() as session:
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise HTTPException(404, "Employee not found")
        rows = (await session.execute(
            select(SalaryViolation)
            .where(SalaryViolation.employee_id == employee_id, SalaryViolation.created_at >= start_dt)
            .order_by(desc(SalaryViolation.created_at))
            .limit(500)
        )).scalars().all()
    return {
        "employee": {"id": employee.id, "name": employee.full_name or f"Сотрудник #{employee.id}"},
        "days": days,
        "items": [{
            "id": v.id, "rule_code": v.rule_code, "title": v.title, "amount": dec(v.amount),
            "comment": v.comment, "created_at": iso(v.created_at), "shift_id": v.shift_id,
        } for v in rows],
    }


async def create_penalty(request: Request, payload: PenaltyCreate):
    user, _ = await current_user(request)
    owner_required(user)
    rule = RULES.get(payload.rule_code)
    if not rule:
        raise HTTPException(400, "Unknown penalty rule")
    async with SessionLocal() as session:
        employee = await session.get(Employee, payload.employee_id)
        if not employee or not employee.active:
            raise HTTPException(404, "Employee not found")
        violation = SalaryViolation(
            employee_id=employee.id,
            rule_code=rule["code"],
            title=rule["title"],
            amount=rule["amount"],
            source="manual",
            shift_id=payload.shift_id,
            premium_reduction_percent=0,
            dismissal_required=False,
            comment=payload.comment,
            created_by=user.telegram_id,
        )
        session.add(violation)
        await session.commit()
        await session.refresh(violation)
        return {"id": violation.id, "employee_id": employee.id, "rule_code": rule["code"], "title": rule["title"], "amount": rule["amount"]}


JS = r'''async function adminPenalties(id){clear();setBottom(false);back();const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const d=await api(`/api/admins/${Number(id)}/penalties?days=365`);const items=d.items||[];root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Штрафы · ${esc(d.employee.name)}</h2><span>${items.length}</span></div><button class="primary" onclick="adminPenaltyForm(${Number(id)})">+ Начислить штраф</button><div class="nav-card" style="margin-top:10px">${items.length?items.map(v=>`<div class="row"><div class="row-main"><div class="row-title">${esc(v.title)}</div><div class="row-sub">${v.created_at?new Date(v.created_at).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—'}${v.comment?' · '+esc(v.comment):''}</div></div><div class="row-value">${money(v.amount)}</div></div>`).join(''):'<div class="empty">Штрафов за период нет</div>'}</div>`)}
async function adminPenaltyForm(id){clear();setBottom(false);back();const d=await api('/api/penalty-rules');const groups={250:[],500:[],1000:[],2000:[]};(d.items||[]).forEach(r=>groups[r.amount]?.push(r));let html='';Object.entries(groups).forEach(([amount,items])=>{if(!items.length)return;html+=`<div class="section-title"><h2>${amount} ₽</h2></div><div class="nav-card">${items.map(r=>`<button class="nav-btn" onclick="adminPenaltyConfirm(${Number(id)},'${r.code}')"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">${esc(r.title)}</span></span><span class="nav-arrow">›</span></button>`).join('')}</div>`});root.insertAdjacentHTML('beforeend',`<div class="section-title"><h2>Выберите нарушение</h2></div>${html}`)}
async function adminPenaltyConfirm(id,code){const d=await api('/api/penalty-rules');const r=(d.items||[]).find(x=>x.code===code);if(!r)return;const comment=prompt(`Штраф ${r.amount} ₽\n${r.title}\n\nКомментарий (необязательно):`,'');if(comment===null)return;try{await api('/api/admins/penalties',{method:'POST',body:JSON.stringify({employee_id:Number(id),rule_code:code,comment:comment||null})});alert('Штраф начислен');adminPenalties(id)}catch(e){fail(e)}}'''


async def install_index():
    return None


def install(web_app):
    web_app.add_api_route("/api/penalty-rules", penalty_rules, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/admins/{employee_id}/penalties", employee_penalties, methods=["GET"], include_in_schema=False)
    web_app.add_api_route("/api/admins/penalties", create_penalty, methods=["POST"], include_in_schema=False)
    for route in web_app.routes:
        if isinstance(route, APIRoute) and route.path == "/":
            break
'''}