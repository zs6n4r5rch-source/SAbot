from fastapi.routing import APIRoute


def compose_page(html: str) -> str:
    from app.webapp.work_center_v3 import JS as work_js
    from app.webapp.management_dashboard import JS as management_js
    from app.webapp.current_summary import JS as summary_js
    from app.webapp.current_summary_v3 import JS as summary_v3_js
    from app.webapp.admin_shift_control import JS as admin_js
    from app.webapp.admin_penalties_ui import JS as penalties_ui_js
    admin_guard = r'''<script>
(function(){
  const ownerHome=window.home;
  window.home=async function(){
    if(me?.role!=="admin") return ownerHome?.();
    clear();setBottom(true);
    try{
      const d=await api("/api/shifts?days=30"); const rows=d.items||[]; const current=rows.find(x=>x.status==="open");
      root.innerHTML=`<section class="hero"><div class="eyebrow">МОИ СМЕНЫ</div><div class="hero-title">${me.display_name||"Администратор"}</div><div class="hero-sub">Только ваши смены, отчёты, начисления и нарушения.</div></section>`;
      root.insertAdjacentHTML("beforeend",`<div class="section-title"><h2>Текущая смена</h2></div><section class="card">${current?row("Статус","Открыта",current.started_at||"")+row("Наличные",money(current.cash_sales))+row("Карта",money(current.card_sales))+row("Онлайн",money(current.mobile_sales))+row("Разница кассы",current.cash_difference==null?"—":money(current.cash_difference)):"<div class=\"empty\">Открытой смены нет</div>"}</section>`);
      root.insertAdjacentHTML("beforeend",`<div class="section-title"><h2>Мои разделы</h2></div><div class="nav-card"><button class="nav-btn" onclick="shifts()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Мои смены</span><span class="nav-hint">История и статусы</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="salary()"><span class="nav-icon">₽</span><span class="nav-copy"><span class="nav-label">Моя зарплата</span><span class="nav-hint">Начисления</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="bonuses()"><span class="nav-icon">+</span><span class="nav-copy"><span class="nav-label">Мои бонусы</span><span class="nav-hint">Поощрения</span></span><span class="nav-arrow">›</span></button></div>`);
      root.insertAdjacentHTML("beforeend",`<div class="card muted">Закрытие смены и обязательный отчёт выполняются штатным сценарием Telegram; в приложении администратор видит только собственные данные.</div>`);
    }catch(e){fail(e)}
  };
  window.goNav=function(which){if(which==="home")return window.home();if(which==="work")return me?.role==="owner"?(window.workCenter?window.workCenter():window.home()):window.shifts();if(which==="more")return me?.role==="owner"?(window.settings?window.settings():window.home()):(window.bonuses?window.bonuses():window.home())};
})();
</script>'''
    return html.replace('</body>', '\n'.join((work_js, management_js, summary_js, summary_v3_js, admin_js, penalties_ui_js, admin_guard))+'</body>', 1)


def install(web_app):
    for route in list(web_app.routes):
        if isinstance(route, APIRoute) and route.path == '/':
            web_app.routes.remove(route)
    from app.webapp.app import index
    web_app.add_api_route('/', index, methods=['GET'], include_in_schema=False)
