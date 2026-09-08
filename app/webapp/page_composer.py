from fastapi.routing import APIRoute
from fastapi import Request
from fastapi.responses import JSONResponse


def compose_page(html: str) -> str:
    from app.webapp.work_center_v3 import JS as work_js
    from app.webapp.management_dashboard import JS as management_js
    from app.webapp.current_summary import JS as summary_js
    from app.webapp.current_summary_v3 import JS as summary_v3_js
    from app.webapp.admin_shift_control import JS as admin_js
    from app.webapp.admin_penalties_ui import JS as penalties_ui_js
    admin_guard=r'''<script>
(function(){
const ownerHome=window.home;
const ownerWork=window.workCenter;
const wallTime=v=>{const m=String(v??'').match(/T(\d{2}:\d{2})/);return m?m[1]:'—'};
const ownerEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ownerMoney=v=>v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const localDate=()=>new Date().toLocaleDateString('sv-SE');
const wcHomeBack=()=>root.prepend(btn('← На главную',home,'back'));
const wcBackHome=()=>root.prepend(btn('← На главную',home,'back'));
const wcBackCenter=()=>root.prepend(btn('← Рабочая зона',workCenter,'back'));

window.currentGroupGuests=async function(id){
  clear();setBottom(false);try{const d=await api(`/api/current-summary/guests?group_id=${Number(id)}`);const items=d.items||[];root.innerHTML=`<section class="hero"><div class="eyebrow">ЛОЯЛЬНОСТЬ</div><div class="hero-title">${ownerEsc(d.group?.name||'Группа')}</div><div class="hero-sub">${items.length} гостей</div></section><div class="nav-card">${items.map(g=>`<section class="card"><div class="admin-name">${ownerEsc(g.fio)}</div><div class="admin-meta">LANGAME #${ownerEsc(g.langame_guest_id)}${g.phone?' · '+ownerEsc(g.phone):''}</div></section>`).join('')||'<div class="empty">Гостей в этой группе нет</div>'}</div>`;wcBackCenter()}catch(e){fail(e)}};

window.workCenter=async function(){
  if(me?.role!=="owner")return ownerWork?.();
  clear();setBottom(false);
  try{
    const [d,s]=await Promise.all([api('/api/work-center-v3'),api('/api/current-summary')]);
    const hall=d.hall||{}, wh=d.warehouse||{}, control=d.control||{};
    const groups=(s.guests?.groups||[]).slice(0,12).map(g=>`<button class="nav-btn" onclick="currentGroupGuests(${Number(g.id)})"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">${ownerEsc(g.name)}</span><span class="nav-hint">${Number(g.count||0)} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');
    root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель владельца.</div><div class="row-sub">Обновлено ${wallTime(d.updated_at)}, Москва.</div></section>
      <div class="section-title"><h2>Зал</h2><span>${hall.active_sessions??'—'}</span></div><div class="nav-card"><button class="nav-btn" onclick="workGuestsNow()"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">Гости сейчас</span><span class="nav-hint">Активные сессии · ${hall.active_sessions??'—'}</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Гости и лояльность</h2><span>${s.guests?.total??0}</span></div><div class="nav-card">${groups||'<div class="empty">Группы лояльности не найдены</div>'}</div>
      <div class="section-title"><h2>Финансы</h2><span>выручка · расходы · прибыль</span></div><div class="nav-card"><button class="nav-btn" onclick="workFinance()"><span class="nav-icon">💰</span><span class="nav-copy"><span class="nav-label">Финансы клуба</span><span class="nav-hint">Игровое время · еда и услуги · закупочная себестоимость</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Смены и отчёты</h2></div><div class="nav-card"><button class="nav-btn" onclick="previousShift()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Предыдущая смена</span><span class="nav-hint">Последний завершённый отчёт</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Склад</h2><span>${wh.critical??0}</span></div><div class="nav-card"><button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Склад по категориям</span><span class="nav-hint">Энергетики · закуски · напитки и другие категории</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${wh.critical??0} позиций</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Контроль</h2><span>${(control.open_without_report||0)+(control.critical_stock||0)}</span></div><div class="nav-card"><button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Открыть контроль</span><span class="nav-hint">Смены без отчёта и критические остатки</span></span><span class="nav-arrow">›</span></button></div>`;
    wcHomeBack();
  }catch(e){fail(e)}
};

window.previousShift=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3');const r=(d.reports||[]).find(x=>x.id);if(!r){root.innerHTML='<div class="empty">Предыдущей завершённой смены пока нет</div>';wcBackCenter();return}return shiftReportOpen(Number(r.id))}catch(e){fail(e)}};
window.shiftReports=window.previousShift;

window.workFinance=async function(){clear();setBottom(false);root.innerHTML=`<section class="hero"><div class="eyebrow">ФИНАНСЫ КЛУБА</div><div class="hero-title">Выручка, расходы и прибыль</div><div class="hero-sub">Еда и напитки включены сюда. Себестоимость считается по конкретно проданным товарам.</div></section><section class="card"><div class="row"><div class="row-main"><div class="row-title">От</div></div><input id="finFrom" type="date" value="${localDate()}"></div><div class="row"><div class="row-main"><div class="row-title">До</div></div><input id="finTo" type="date" value="${localDate()}"></div><button class="primary" onclick="loadFinance()">Показать период</button></section><div id="finOut"><div class="empty">Загрузка…</div></div>`;wcBackCenter();await loadFinance()};
window.loadFinance=async function(){const f=document.getElementById('finFrom')?.value,t=document.getElementById('finTo')?.value;if(!f||!t)return;try{const d=await api(`/api/work-center-v3/finance?date_from=${f}&date_to=${t}`);document.getElementById('finOut').innerHTML=`<section class="card">${wcRow('Игровое время — выручка',ownerMoney(d.gaming))}${wcRow('Еда и услуги — выручка',ownerMoney(d.bar_sales))}${wcRow('Общая выручка',ownerMoney((d.gaming||0)+(d.bar_sales||0)))}${wcRow('Себестоимость проданных товаров',ownerMoney(d.bar_purchases))}${wcRow('Валовая прибыль',ownerMoney(d.bar_profit))}</section><section class="card"><div class="section-title"><h2>Что входит в расчёт</h2></div>${wcRow('Основа',d.purchase_basis||'Себестоимость конкретно проданных товаров')}${wcRow('Источник',d.source||'LANGAME')}</section>`}catch(e){fail(e)}};

window.shiftReportOpen=async function(id){if(!id)return;clear();setBottom(false);try{const d=await api('/api/work-center-v3/reports/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">ПРЕДЫДУЩАЯ СМЕНА</div><div class="hero-title">${ownerEsc(d.employee)}</div><div class="hero-sub">${wallTime(d.started_at)} — ${wallTime(d.ended_at)} · ${ownerEsc(d.club)}</div></section><section class="card">${wcRow('Статус',d.status==='submitted'?'Сдан':'Не завершён')}${wcRow('Расчётная наличность',ownerMoney(d.cash_expected))}${wcRow('Фактическая наличность',ownerMoney(d.cash_actual))}${wcRow('Разница кассы',d.cash_difference==null?'—':ownerMoney(d.cash_difference))}${wcRow('Проверено товаров',d.stock_items_count??'—')}${wcRow('Расхождений по товарам',d.stock_discrepancies_count??0)}${d.handover_note?wcRow('Передача смены',d.handover_note):''}</section>`;wcBackCenter()}catch(e){fail(e)}};

window.workWarehouse=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Склад по категориям</div></section><div class="nav-card">${(d.warehouse?.categories||[]).map(c=>`<button class="nav-btn" onclick="warehouseCategory(${Number(c.id)})"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${ownerEsc(c.name)}</span><span class="nav-hint">${c.count} позиций</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Категории склада не найдены</div>'}</div><button class="primary" onclick="criticalStock()">Критические остатки</button>`;wcBackCenter()}catch(e){fail(e)}};
window.warehouseCategory=async function(id){clear();setBottom(false);try{const d=await api('/api/work-center-v3/categories/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД · КАТЕГОРИЯ</div><div class="hero-title">Товары</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${ownerEsc(x.product)}</div><div class="row-sub">${ownerEsc(x.club)}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')||'<div class="empty">В категории нет товаров</div>'}</div>`;wcBackCenter()}catch(e){fail(e)}};
window.criticalStock=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3/critical');root.innerHTML=`<section class="hero"><div class="eyebrow">КРИТИЧЕСКИЕ ОСТАТКИ</div><div class="hero-title">${(d.items||[]).length} позиций</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${ownerEsc(x.product)}</div><div class="row-sub">${ownerEsc(x.category)} · ${ownerEsc(x.club)}</div></div><div class="row-value">${x.quantity} / ${x.min_stock}</div></div>`).join('')||'<div class="empty">Критических остатков нет</div>'}</div>`;wcBackCenter()}catch(e){fail(e)}};
window.workControl=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3');const c=d.control||{};root.innerHTML=`<section class="hero"><div class="eyebrow">КОНТРОЛЬ</div><div class="hero-title">Что требует действия</div></section><div class="nav-card">${c.open_without_report?`<button class="nav-btn" onclick="previousShift()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Смены без отчёта</span><span class="nav-hint">${c.open_without_report}</span></span><span class="nav-arrow">›</span></button>`:''}${c.critical_stock?`<button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${c.critical_stock}</span></span><span class="nav-arrow">›</span></button>`:''}${!(c.open_without_report||c.critical_stock)?'<div class="empty">Критических действий нет</div>':''}</div>`;wcBackCenter()}catch(e){fail(e)}};

window.home=async function(){if(me?.role!=="owner")return ownerHome?.();clear();setBottom(true);try{const d=await api('/api/current-summary');document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;const shiftHtml=d.shifts.length?d.shifts.map(s=>`<div class="row"><div class="row-main"><div class="row-title">🟢 ${ownerEsc(s.employee)}</div><div class="row-sub">На смене ${currentFmtDuration(s.duration_minutes)} · с ${wallTime(s.started_at)}</div></div><div class="row-value">${ownerMoney(s.sales)}</div></div>`).join(''):'<div class="empty">Сейчас открытых смен нет</div>';const attention=d.attention.critical_total;root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Смены, выручка, отчёты и проблемы. Обновлено ${wallTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><section class="card">${shiftHtml}</section><div class="grid"><section class="card"><div class="section-title"><h2>Выручка сегодня</h2></div>${row('Бар и снеки',ownerMoney(d.sales.bar))}${row('Игровое время',ownerMoney(d.sales.gaming))}<div class="row"><div class="row-main"><div class="row-title">Всего</div></div><div class="row-value">${ownerMoney(d.sales.bar+d.sales.gaming)}</div></div></section><section class="card"><div class="section-title"><h2>Смены и отчёты</h2></div>${row('Отчёты сданы',d.reports.submitted)}${row('Ожидают отчёта',d.reports.pending)}${row('Открытые смены без отчёта',d.reports.open_without_report)}</section></div><div class="section-title"><h2>Требует внимания</h2><span>${attention}</span></div><section class="nav-card">${d.attention.critical_stock?`<button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${d.attention.critical_stock} позиций</span></span><span class="nav-arrow">›</span></button>`:''}${d.attention.dismissal_required?`<button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Требуется решение по нарушениям</span><span class="nav-hint">${d.attention.dismissal_required}</span></span><span class="nav-arrow">›</span></button>`:''}${!attention?'<div class="empty">Сейчас ничего не требует внимания</div>':''}</section>`}catch(e){fail(e)}};
window.goNav=function(which){if(which==="home")return window.home();if(which==="work")return me?.role==="owner"?window.workCenter():(window.shifts?window.shifts():window.home());if(which==="more")return me?.role==="owner"?(window.settings?window.settings():window.home()):(window.bonuses?window.bonuses():window.home())};
})();
</script>'''
    return html.replace('</body>','\n'.join((work_js,management_js,summary_js,summary_v3_js,admin_js,penalties_ui_js,admin_guard))+'</body>',1)


async def _langame_group_guests(request: Request, group_id: int):
    from app.services.langame import LangameAPIError, langame_client
    from app.webapp.app import current_user, owner_required
    user, _ = await current_user(request)
    owner_required(user)
    try:
        payload = await langame_client.guests_search(groups=[int(group_id)], size=100, page=1)
        rows = payload.get("data") or payload.get("items") or payload.get("results") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("data") or []
        return {"group":{"id":int(group_id),"name":"Группа LANGAME"},"items":[{"langame_guest_id":r.get("guest_id",r.get("id")),"fio":r.get("fio") or r.get("name") or "Без имени","phone":r.get("phone") or ""} for r in rows if isinstance(r,dict)]}
    except (LangameAPIError, TypeError, ValueError) as exc:
        return JSONResponse({"group":{"id":int(group_id),"name":"Группа LANGAME"},"items":[],"error":str(exc)},status_code=502)


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route,APIRoute) and route.path=='/': web_app.routes.remove(route)
    from app.webapp.app import index
    web_app.add_api_route('/',index,methods=['GET'],include_in_schema=False)
    web_app.add_api_route('/api/current-summary/langame-guests',_langame_group_guests,methods=['GET'],include_in_schema=False)
