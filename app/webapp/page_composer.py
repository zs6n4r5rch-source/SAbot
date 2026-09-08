from fastapi.routing import APIRoute

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
window.workCenter=async function(){
  if(me?.role!=="owner")return ownerWork?.();
  clear();setBottom(false);
  try{
    const [d,s]=await Promise.all([api('/api/work-center-v3'),api('/api/current-summary')]);
    const hall=d.hall||{}, bar=d.bar||{}, wh=d.warehouse||{}, control=d.control||{};
    const groups=(s.guests?.groups||[]).slice(0,8).map(g=>`<button class="nav-btn" onclick="currentGroupGuests(${Number(g.id)})"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">${ownerEsc(g.name)}</span><span class="nav-hint">${Number(g.count||0)} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');
    root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель владельца.</div><div class="row-sub">Обновлено ${wallTime(d.updated_at)}, Москва.</div></section>
      <div class="section-title"><h2>Зал</h2><span>${hall.active_sessions??'—'}</span></div>
      <div class="nav-card"><button class="nav-btn" onclick="workGuestsNow()"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">Гости сейчас</span><span class="nav-hint">Активные сессии · ${hall.active_sessions??'—'}</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Бар и снеки</h2><span>Прибыль</span></div><section class="card">${wcRow('Продажи',wcMoney(bar.sales))}${wcRow('Закупки',wcMoney(bar.purchases))}${wcRow('Прибыль',wcMoney(bar.profit))}</section>
      <div class="section-title"><h2>Гости и лояльность</h2><span>${s.guests?.total??0}</span></div><div class="nav-card">${groups||'<div class="empty">Группы лояльности не найдены</div>'}</div>
      <div class="section-title"><h2>Финансы</h2></div><div class="nav-card"><button class="nav-btn" onclick="workFinance()"><span class="nav-icon">💰</span><span class="nav-copy"><span class="nav-label">Финансы</span><span class="nav-hint">Gaming · бар · произвольный период</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Смены и отчёты</h2><span>${(d.reports||[]).length}</span></div><div class="nav-card"><button class="nav-btn" onclick="shiftReports()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Отчёты о сменах</span><span class="nav-hint">Касса · остатки · передача смены</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Склад</h2><span>${wh.critical??0}</span></div><div class="nav-card"><button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Полный склад</span><span class="nav-hint">Категории и остатки</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${wh.critical??0} позиций</span></span><span class="nav-arrow">›</span></button></div>
      <div class="section-title"><h2>Контроль</h2><span>${(control.open_without_report||0)+(control.critical_stock||0)}</span></div><div class="nav-card"><button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Открыть контроль</span><span class="nav-hint">Смены, отчёты, остатки и нарушения</span></span><span class="nav-arrow">›</span></button></div>`;
  }catch(e){fail(e)}
};
window.home=async function(){
  if(me?.role!=="owner")return ownerHome?.();
  clear();setBottom(true);
  try{
    const d=await api('/api/current-summary');
    document.getElementById('hello').textContent=`${me.display_name||'Пользователь'} · Владелец`;
    const shiftHtml=d.shifts.length?d.shifts.map(s=>`<div class="row"><div class="row-main"><div class="row-title">🟢 ${ownerEsc(s.employee)}</div><div class="row-sub">На смене ${currentFmtDuration(s.duration_minutes)} · с ${wallTime(s.started_at)}</div></div><div class="row-value">${ownerMoney(s.sales)}</div></div>`).join(''):'<div class="empty">Сейчас открытых смен нет</div>';
    const attention=d.attention.critical_total;
    root.innerHTML=`<section class="hero"><div class="eyebrow">ТЕКУЩАЯ СВОДКА</div><div class="hero-title">Что происходит сейчас</div><div class="hero-sub">Смены, выручка, отчёты и проблемы. Обновлено ${wallTime(d.updated_at)}, Москва.</div></section><div class="section-title"><h2>Сейчас на смене</h2><span>${d.shifts.length}</span></div><section class="card">${shiftHtml}</section><div class="grid"><section class="card"><div class="section-title"><h2>Выручка сегодня</h2></div>${row('Бар и снеки',ownerMoney(d.sales.bar))}${row('Игровое время',ownerMoney(d.sales.gaming))}${d.sales.other?row('Прочее',ownerMoney(d.sales.other)):''}<div class="row"><div class="row-main"><div class="row-title">Всего</div></div><div class="row-value">${ownerMoney(d.sales.bar+d.sales.gaming+d.sales.other)}</div></div></section><section class="card"><div class="section-title"><h2>Смены и отчёты</h2></div>${row('Отчёты сданы',d.reports.submitted)}${row('Ожидают отчёта',d.reports.pending)}${row('Открытые смены без отчёта',d.reports.open_without_report)}</section></div><div class="section-title"><h2>Требует внимания</h2><span>${attention}</span></div><section class="card">${row('Критические остатки',d.attention.critical_stock)}${row('Требуется решение по нарушениям',d.attention.dismissal_required)}${row('Критические позиции / проблемы',attention)}</section>`;
  }catch(e){fail(e)}
};
window.goNav=function(which){if(which==="home")return window.home();if(which==="work")return me?.role==="owner"?(window.workCenter?window.workCenter():ownerWork?ownerWork():window.home()):window.shifts();if(which==="more")return me?.role==="owner"?(window.settings?window.settings():window.home()):(window.bonuses?window.bonuses():window.home())};
})();
</script>'''
    return html.replace('</body>','\n'.join((work_js,management_js,summary_js,summary_v3_js,admin_js,penalties_ui_js,admin_guard))+'</body>',1)

def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route,APIRoute) and route.path=='/': web_app.routes.remove(route)
    from app.webapp.app import index
    web_app.add_api_route('/',index,methods=['GET'],include_in_schema=False)
