from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select


def install():
    from app.webapp.app import app, current_user, owner_required
    from app.db.session import SessionLocal
    from app.models import InventoryBalance, Product, ProductCategory, Club, Shift, Employee, ShiftCloseReport
    from app.services.langame import langame_client
    import app.webapp.page_composer as pc

    async def owner(request: Request):
        user, _ = await current_user(request)
        owner_required(user)

    async def previous_shift(request: Request):
        await owner(request)
        async with SessionLocal() as session:
            row = (await session.execute(
                select(ShiftCloseReport, Shift, Employee, Club)
                .join(Shift, Shift.id == ShiftCloseReport.shift_id)
                .outerjoin(Employee, Employee.id == Shift.employee_id)
                .outerjoin(Club, Club.id == Shift.club_id)
                .where(Shift.ended_at.is_not(None), ShiftCloseReport.status == "submitted")
                .order_by(Shift.ended_at.desc())
                .limit(1)
            )).first()
        if not row:
            return {"report": None}
        report, shift, employee, club = row
        return {"report": {
            "id": report.id,
            "employee": employee.full_name if employee else f"Администратор #{shift.employee_id}",
            "club": club.name if club else "—",
        }}

    async def warehouse_categories(request: Request):
        await owner(request)
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(InventoryBalance, Product, Club, ProductCategory)
                .join(Product, Product.id == InventoryBalance.product_id)
                .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
                .join(Club, Club.id == InventoryBalance.club_id)
                .order_by(ProductCategory.name, Product.name, Club.name)
            )).all()
        groups = {}
        for balance, product, club, category in rows:
            key = int(category.id) if category else 0
            name = category.name if category else "Без категории"
            group = groups.setdefault(key, {"id": key, "name": name, "count": 0})
            group["count"] += 1
        return {"categories": list(groups.values())}

    async def warehouse_category(request: Request, category_id: int):
        await owner(request)
        async with SessionLocal() as session:
            query = (
                select(InventoryBalance, Product, Club)
                .join(Product, Product.id == InventoryBalance.product_id)
                .join(Club, Club.id == InventoryBalance.club_id)
            )
            if category_id == 0:
                query = query.where(Product.category_id.is_(None))
            else:
                query = query.where(Product.category_id == category_id)
            rows = (await session.execute(query.order_by(Product.name, Club.name))).all()
        return {"category_id": category_id, "items": [
            {"id": b.id, "product": p.name, "club": club.name,
             "quantity": float(b.quantity or 0), "min_stock": float(b.min_stock or 0)}
            for b, p, club in rows
        ]}

    async def group_guests(request: Request, group_id: int):
        await owner(request)
        try:
            payload = await langame_client.guests_search(groups=[group_id], size=100, page=1)
        except Exception as exc:
            return JSONResponse({"items": [], "error": str(exc)}, status_code=502)
        if isinstance(payload, dict):
            items = payload.get("items") or payload.get("data") or payload.get("results") or payload.get("rows") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        out = []
        for g in items:
            if not isinstance(g, dict):
                continue
            gid = g.get("id") or g.get("guest_id") or g.get("guestId")
            out.append({
                "fio": g.get("fio") or g.get("name") or g.get("full_name") or f"Гость #{gid}",
                "langame_guest_id": gid,
                "phone": g.get("phone"),
            })
        return {"items": out}

    existing = {getattr(r, "path", None) for r in app.routes}
    routes = [
        ("/api/work-center-v3/previous-shift", previous_shift),
        ("/api/work-center-v3/warehouse-categories", warehouse_categories),
        ("/api/work-center-v3/warehouse-category/{category_id}", warehouse_category),
        ("/api/current-summary/langame-guests", group_guests),
    ]
    for path, handler in routes:
        if path not in existing:
            app.add_api_route(path, handler, methods=["GET"])

    original = pc.compose_page
    if getattr(original, "_final_owner_hotfixed", False):
        print("SAbot final owner hotfix already installed", flush=True)
        return

    def compose(html: str) -> str:
        result = original(html)
        script = r'''<script>
(function(){
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const back=()=>root.prepend(btn('← Рабочая зона',window.workCenter,'back'));
window.currentGroupGuests=async function(id,name){clear();setBottom(false);try{const d=await api('/api/current-summary/langame-guests?group_id='+Number(id));const items=d.items||[];root.innerHTML=`<section class="hero"><div class="eyebrow">ЛОЯЛЬНОСТЬ</div><div class="hero-title">${esc(name||'Группа')}</div><div class="hero-sub">${items.length} гостей</div></section><div class="nav-card">${items.map(g=>`<section class="card"><div class="admin-name">${esc(g.fio)}</div><div class="admin-meta">LANGAME #${esc(g.langame_guest_id)}${g.phone?' · '+esc(g.phone):''}</div></section>`).join('')||'<div class="empty">Гостей в этой группе нет</div>'}</div>`;back()}catch(e){fail(e)}};
window.previousShift=async function(){clear();setBottom(false);try{const x=await api('/api/work-center-v3/previous-shift');const r=x.report;if(!r){root.innerHTML='<div class="empty">Предыдущей завершённой смены пока нет</div>';back();return}return shiftReportOpen(Number(r.id))}catch(e){fail(e)}};
window.shiftReports=window.previousShift;
window.workWarehouse=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3/warehouse-categories');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Склад по категориям</div><div class="hero-sub">Все товары сгруппированы по реальной категории LANGAME</div></section><div class="nav-card">${(d.categories||[]).map(c=>`<button class="nav-btn" onclick='warehouseCategory(${Number(c.id)},${JSON.stringify(String(c.name))})'><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${esc(c.name)}</span><span class="nav-hint">${c.count} позиций</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Категории склада не найдены</div>'}</div><button class="primary" onclick="criticalStock()">Критические остатки</button>`;back()}catch(e){fail(e)}};
window.warehouseCategory=async function(id,name){clear();setBottom(false);try{const d=await api('/api/work-center-v3/warehouse-category/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД · КАТЕГОРИЯ</div><div class="hero-title">${esc(name||'Товары')}</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${esc(x.product)}</div><div class="row-sub">${esc(x.club)} · минимум ${x.min_stock}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')||'<div class="empty">В категории нет товаров</div>'}</div>`;back()}catch(e){fail(e)}};
window.criticalStock=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3/critical-categories');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Критические остатки</div><div class="hero-sub">По категориям товаров</div></section>${(d.categories||[]).map(c=>`<section class="card"><div class="section-title"><h2>${esc(c.name)}</h2><span>${c.count}</span></div>${(c.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${esc(x.product)}</div><div class="row-sub">${esc(x.club)} · минимум ${x.min_stock}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')}</section>`).join('')||'<div class="empty">Критических остатков нет</div>'};back()}catch(e){fail(e)}};
window.workFinance=async function(){clear();setBottom(false);root.innerHTML=`<section class="hero"><div class="eyebrow">ФИНАНСЫ КЛУБА</div><div class="hero-title">Выручка, расходы и прибыль</div><div class="hero-sub">Игровое время + еда и услуги. Себестоимость — только проданных товаров.</div></section><section class="card"><div class="row"><div class="row-main"><div class="row-title">От</div></div><input id="finFrom" type="date" value="${new Date().toLocaleDateString('sv-SE')}"></div><div class="row"><div class="row-main"><div class="row-title">До</div></div><input id="finTo" type="date" value="${new Date().toLocaleDateString('sv-SE')}"></div><button class="primary" onclick="loadFinance()">Показать период</button></section><div id="finOut"><div class="empty">Загрузка…</div></div>`;back();await loadFinance()};
window.loadFinance=async function(){const f=document.getElementById('finFrom')?.value,t=document.getElementById('finTo')?.value;if(!f||!t)return;try{const d=await api('/api/work-center-v3/finance?date_from='+f+'&date_to='+t);document.getElementById('finOut').innerHTML=`<section class="card">${wcRow('Игровое время — выручка',money(d.gaming))}${wcRow('Еда и услуги — выручка',money(d.bar_sales))}${wcRow('Общая выручка',money((d.gaming||0)+(d.bar_sales||0)))}${wcRow('Себестоимость проданных товаров',money(d.bar_purchases))}${wcRow('Валовая прибыль',money(d.bar_profit))}</section>`}catch(e){fail(e)}};
window.workCenter=async function(){if(me?.role!=='owner')return;clear();setBottom(false);try{const [d,s]=await Promise.all([api('/api/work-center-v3'),api('/api/current-summary')]);const groups=(s.guests?.groups||[]).slice(0,20).map(g=>`<button class="nav-btn" onclick='currentGroupGuests(${Number(g.id)},${JSON.stringify(String(g.name||'Группа'))})'><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">${esc(g.name||'Группа')}</span><span class="nav-hint">${Number(g.count||0)} гостей</span></span><span class="nav-arrow">›</span></button>`).join('');root.innerHTML=`<section class="hero"><div class="eyebrow">WORK</div><div class="hero-title">Рабочий центр</div><div class="hero-sub">Оперативная панель владельца.</div></section><div class="section-title"><h2>Зал</h2><span>${d.hall?.active_sessions??'—'}</span></div><div class="nav-card"><button class="nav-btn" onclick="workGuestsNow()"><span class="nav-icon">👥</span><span class="nav-copy"><span class="nav-label">Гости сейчас</span><span class="nav-hint">Активные сессии · ${d.hall?.active_sessions??'—'}</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Гости и лояльность</h2><span>${s.guests?.total??0}</span></div><div class="nav-card">${groups||'<div class="empty">Группы лояльности не найдены</div>'}</div><div class="section-title"><h2>Финансы</h2></div><div class="nav-card"><button class="nav-btn" onclick="workFinance()"><span class="nav-icon">💰</span><span class="nav-copy"><span class="nav-label">Финансы клуба</span><span class="nav-hint">Игровое время · еда и услуги · себестоимость</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Смены и отчёты</h2></div><div class="nav-card"><button class="nav-btn" onclick="previousShift()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Предыдущая смена</span><span class="nav-hint">Последний сданный отчёт</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Склад</h2><span>${d.warehouse?.critical??0}</span></div><div class="nav-card"><button class="nav-btn" onclick="workWarehouse()"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">Склад по категориям</span><span class="nav-hint">Все категории, не только критические</span></span><span class="nav-arrow">›</span></button><button class="nav-btn" onclick="criticalStock()"><span class="nav-icon">⚠️</span><span class="nav-copy"><span class="nav-label">Критические остатки</span><span class="nav-hint">${d.warehouse?.critical??0} позиций · тоже по категориям</span></span><span class="nav-arrow">›</span></button></div><div class="section-title"><h2>Контроль</h2><span>${(d.control?.open_without_report||0)+(d.control?.critical_stock||0)}</span></div><div class="nav-card"><button class="nav-btn" onclick="workControl()"><span class="nav-icon">🎯</span><span class="nav-copy"><span class="nav-label">Открыть контроль</span><span class="nav-hint">Смены без отчёта и критические остатки</span></span><span class="nav-arrow">›</span></button></div>`;root.prepend(btn('← На главную',home,'back'))}catch(e){fail(e)}};
})();
</script>'''
        return result + script

    compose._final_owner_hotfixed = True
    pc.compose_page = compose
    print("SAbot final owner hotfix installed", flush=True)
