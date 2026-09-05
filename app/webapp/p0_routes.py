from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Shift, ShiftCloseReport, ShiftCloseStockItem, UserRole
from app.webapp.app import app, current_user, iso, dec


class ShiftCloseStockPayload(BaseModel):
    product_id: int
    actual_quantity: float
    comment: str = Field(default="", max_length=4000)


class ShiftClosePayload(BaseModel):
    actual_cash: float
    stock_items: list[ShiftCloseStockPayload] = Field(default_factory=list)
    cash_comment: str = Field(default="", max_length=4000)
    cleaning_performed_by: str = Field(default="", max_length=255)


def _admin(user):
    if user.role != UserRole.ADMIN.value or not user.employee_id:
        raise HTTPException(403, "ADMIN access required")


@app.get("/api/my-shift")
async def my_shift(request: Request):
    user, _ = await current_user(request)
    _admin(user)
    from app.bot.salary import sync_shifts_data
    await sync_shifts_data()
    async with SessionLocal() as session:
        shift = (await session.execute(select(Shift).where(Shift.employee_id == user.employee_id).order_by(Shift.started_at.desc()).limit(1))).scalar_one_or_none()
        if shift is None:
            return {"state": "none"}
        report = await session.scalar(select(ShiftCloseReport).where(ShiftCloseReport.shift_id == shift.id))
        state = "open" if shift.ended_at is None else ("closed" if report and report.status == "submitted" else "awaiting_report")
        return {"state": state, "id": shift.id, "langame_shift_id": shift.langame_shift_id, "started_at": iso(shift.started_at), "ended_at": iso(shift.ended_at), "cash_sales": dec(shift.cash_sales), "card_sales": dec(shift.card_sales), "mobile_sales": dec(shift.mobile_sales), "refunds_cash": dec(shift.refunds_cash), "refunds_card": dec(shift.refunds_card), "collection": dec(shift.collection), "actual_cash": dec(shift.actual_cash), "cash_difference": dec(shift.cash_difference), "report_id": report.id if report else None, "report_status": report.status if report else None}


@app.get("/api/my-shift-close")
async def my_shift_close(request: Request):
    user, _ = await current_user(request)
    _admin(user)
    from app.bot.salary import sync_shifts_data
    from app.bot.shift_closing import _load_langame_stock, _get_or_create_report, cleaning_required_for_shift
    await sync_shifts_data()
    async with SessionLocal() as session:
        shift = (await session.execute(select(Shift).where(Shift.employee_id == user.employee_id).order_by(Shift.started_at.desc()).limit(1))).scalar_one_or_none()
        if shift is None:
            raise HTTPException(404, "Shift not found")
        if shift.ended_at is None or shift.status != "closed":
            raise HTTPException(409, "Смена ещё открыта в LANGAME. Сначала завершите смену там.")
        report = await _get_or_create_report(session, shift)
        expected = await _load_langame_stock(shift, session)
        cleaning_required = await cleaning_required_for_shift(session, shift)
        await session.commit()
        return {"shift": {"id": shift.id, "langame_shift_id": shift.langame_shift_id, "started_at": iso(shift.started_at), "ended_at": iso(shift.ended_at)}, "report": {"id": report.id, "status": report.status, "cash_expected": dec(report.cash_expected), "cash_actual": dec(report.cash_actual), "cash_difference": dec(report.cash_difference), "stock_discrepancies_count": report.stock_discrepancies_count or 0, "cleaning_required": cleaning_required}, "expected_stock": expected}


@app.post("/api/my-shift-close")
async def submit_my_shift_close(request: Request, payload: ShiftClosePayload):
    user, _ = await current_user(request)
    _admin(user)
    from app.bot.salary import sync_shifts_data
    from app.bot.shift_closing import _load_langame_stock, _get_or_create_report, cleaning_required_for_shift, _submit_report, _money, _qty
    await sync_shifts_data()
    async with SessionLocal() as session:
        shift = (await session.execute(select(Shift).where(Shift.employee_id == user.employee_id).order_by(Shift.started_at.desc()).limit(1))).scalar_one_or_none()
        if shift is None:
            raise HTTPException(404, "Shift not found")
        if shift.ended_at is None or shift.status != "closed":
            raise HTTPException(409, "Смена ещё открыта в LANGAME. Сначала завершите смену там.")
        report = await _get_or_create_report(session, shift)
        if report.status == "submitted":
            return {"ok": True, "state": "already_submitted", "report_id": report.id, "shift_id": shift.id, "cash_difference": dec(report.cash_difference), "stock_discrepancies_count": report.stock_discrepancies_count or 0}
        if report.cash_expected is None:
            report.cash_expected = _money((shift.cash_sales or 0) - (shift.refunds_cash or 0) - (shift.collection or 0))
        report.cash_actual = _money(payload.actual_cash)
        report.cash_difference = _money(report.cash_actual - _money(report.cash_expected))
        shift.actual_cash = report.cash_actual
        shift.cash_difference = report.cash_difference
        report.cash_comment = payload.cash_comment.strip()[:4000] or None
        expected = await _load_langame_stock(shift, session)
        supplied = {int(x.product_id): x for x in payload.stock_items}
        missing = [x for x in expected if int(x["product_id"]) not in supplied]
        if missing:
            raise HTTPException(400, {"message": "Укажите фактический остаток по всем товарам.", "missing": missing})
        for item in expected:
            data = supplied[int(item["product_id"])]
            row = await session.scalar(select(ShiftCloseStockItem).where(ShiftCloseStockItem.report_id == report.id, ShiftCloseStockItem.product_id == int(item["product_id"])))
            if row is None:
                row = ShiftCloseStockItem(report_id=report.id, product_id=int(item["product_id"]), langame_quantity=_qty(item["expected"]))
                session.add(row)
            row.actual_quantity = _qty(data.actual_quantity)
            row.difference = row.actual_quantity - row.langame_quantity
            row.comment = data.comment.strip()[:4000] or None
        report.stock_items_count = len(expected)
        report.stock_discrepancies_count = sum(1 for item in expected if _qty(supplied[int(item["product_id"])].actual_quantity) != _qty(item["expected"]))
        if await cleaning_required_for_shift(session, shift):
            if not payload.cleaning_performed_by.strip():
                raise HTTPException(400, "Для этой смены нужно указать, кто выполнил уборку.")
            report.cleaning_confirmed_at = datetime.now(timezone.utc)
            report.cleaning_performed_by = payload.cleaning_performed_by.strip()[:255]
        await _submit_report(session, report, shift, user.telegram_id)
        await session.commit()
        return {"ok": True, "state": "submitted", "report_id": report.id, "shift_id": shift.id, "cash_expected": dec(report.cash_expected), "cash_actual": dec(report.cash_actual), "cash_difference": dec(report.cash_difference), "stock_discrepancies_count": report.stock_discrepancies_count or 0, "cleaning_performed_by": report.cleaning_performed_by}


@app.middleware("http")
async def p0_mini_app_ux(request: Request, call_next):
    if request.url.path != "/":
        return await call_next(request)
    from pathlib import Path
    html = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
    old_group = "['Операции','Бар и контроль смен',['▣','Бар и снеки','Остатки и критические позиции',inventory],['!','Штрафы','Нарушения и решения',penalties]]"
    new_group = "['Операции','Бар и контроль',['▣','Бар и снеки','Остатки и критические позиции',inventory]],['Люди','Сотрудники и контроль',['👥','Администраторы','Управление доступом',admins],['!','Нарушения','Нарушения и решения',penalties]]"
    html = html.replace(old_group, new_group)
    html = html.replace("['✓','Закрытие смены','Завершить рабочий день',()=>alert('Закрытие смены выполняется через рабочий экран бота.')]", "['✓','Закрытие смены','Завершить рабочий день',closeShift]")
    if "async function closeShift()" not in html:
        fn = r'''
async function closeShift(){
  clear();setBottom(false);back();
  try{
    const d=await api('/api/my-shift');
    if(d.state==='none'){root.insertAdjacentHTML('beforeend',card('Смена','Нет смены за текущий период.'));return}
    if(d.state==='open'){root.insertAdjacentHTML('beforeend',card('Смена открыта',`<div class="row"><div class="row-main"><div class="row-title">Смена #${d.langame_shift_id}</div><div class="row-sub">${d.started_at||''}</div></div><div class="row-value">В работе</div></div><p class="muted">Завершение самой смены выполняется в LANGAME. После этого здесь появится отчёт.</p>`));return}
    if(d.report_status==='submitted'){root.insertAdjacentHTML('beforeend',card('Смена закрыта',`<p>Отчёт уже принят.</p>${row('Разница по кассе',money(d.cash_difference))}`));return}
    const close=await api('/api/my-shift-close');let stock=close.expected_stock||[];
    root.innerHTML=`<section class="hero"><div class="eyebrow">Закрытие</div><div class="hero-title">Отчёт по смене #${close.shift.langame_shift_id}</div><div class="hero-sub">Фактическая касса и остатки.</div></section><section class="card"><label>Фактическая наличность, ₽</label><input id="close-cash" type="number" min="0" step="0.01" value="${close.report.cash_expected||0}"><label>Комментарий по кассе</label><textarea id="close-cash-comment" placeholder="Необязательно"></textarea></section><section class="card"><div class="section-title"><h2>Остатки товаров</h2><span>${stock.length} поз.</span></div>${stock.map(x=>`<label>${x.name} · LANGAME ${x.expected}</label><input class="close-stock" data-product="${x.product_id}" type="number" min="0" step="0.001" placeholder="Факт">`).join('')}</section>${close.report.cleaning_required?'<section class="card"><label>Кто выполнил уборку</label><input id="cleaning-performer" placeholder="Имя / ФИО"></section>':''}<button id="submit-close" class="primary">Принять отчёт</button>`;
    document.getElementById('submit-close').onclick=async()=>{try{const items=[...document.querySelectorAll('.close-stock')].map(x=>({product_id:Number(x.dataset.product),actual_quantity:Number(x.value)}));if(items.some(x=>!Number.isFinite(x.actual_quantity))){alert('Заполните фактический остаток по всем товарам.');return}const performer=document.getElementById('cleaning-performer');const r=await api('/api/my-shift-close',{method:'POST',body:JSON.stringify({actual_cash:Number(document.getElementById('close-cash').value),stock_items:items,cash_comment:document.getElementById('close-cash-comment').value,cleaning_performed_by:performer?performer.value:''})});root.innerHTML=card('Отчёт принят',`${row('Разница по кассе',money(r.cash_difference))}${row('Расхождения товаров',r.stock_discrepancies_count)}<p class="muted">Смена зафиксирована. Зарплата пересчитывается по закрытым сменам и начислениям.</p>`) }catch(e){fail(e)}};
  }catch(e){fail(e)}
}
'''
        html = html.replace("\nfunction goNav(which)", "\n" + fn + "\nfunction goNav(which)", 1)
    return HTMLResponse(html)
