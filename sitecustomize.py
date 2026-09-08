# SAbot owner UI hotfixes
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select


def _install_sabot_owner_hotfix():
    try:
        from app.webapp.app import app, current_user, owner_required
        from app.db.session import SessionLocal
        from app.models import InventoryBalance, Product, ProductCategory, Club, Shift, Employee, ShiftCloseReport
        from app.services.langame import langame_client
        import app.webapp.page_composer as pc
    except Exception:
        return

    async def _owner(request):
        user, _ = await current_user(request)
        owner_required(user)

    async def _previous_shift(request: Request):
        await _owner(request)
        async with SessionLocal() as session:
            row = (await session.execute(
                select(ShiftCloseReport, Shift, Employee, Club)
                .join(Shift, Shift.id == ShiftCloseReport.shift_id)
                .outerjoin(Employee, Employee.id == Shift.employee_id)
                .outerjoin(Club, Club.id == Shift.club_id)
                .where(Shift.ended_at.is_not(None), ShiftCloseReport.status == 'submitted')
                .order_by(Shift.ended_at.desc())
                .limit(1)
            )).first()
        if not row:
            return {'report': None}
        report, shift, employee, club = row
        return {'report': {'id': report.id, 'employee': employee.full_name if employee else f'Администратор #{shift.employee_id}', 'club': club.name if club else '—'}}

    async def _warehouse_categories(request: Request):
        await _owner(request)
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(InventoryBalance, Product, Club, ProductCategory)
                .join(Product, Product.id == InventoryBalance.product_id)
                .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
                .join(Club, Club.id == InventoryBalance.club_id)
                .order_by(ProductCategory.name, Product.name)
            )).all()
        groups = {}
        for balance, product, club, category in rows:
            key = int(category.id) if category else 0
            name = category.name if category else 'Без категории'
            if key not in groups:
                groups[key] = {'id': key, 'name': name, 'count': 0}
            groups[key]['count'] += 1
        return {'categories': list(groups.values())}

    async def _warehouse_category(request: Request, category_id: int):
        await _owner(request)
        async with SessionLocal() as session:
            query = select(InventoryBalance, Product, Club).join(Product, Product.id == InventoryBalance.product_id).join(Club, Club.id == InventoryBalance.club_id)
            if category_id:
                query = query.where(Product.category_id == category_id)
            else:
                query = query.where(Product.category_id.is_(None))
            rows = (await session.execute(query.order_by(Product.name))).all()
        return {'category_id': category_id, 'items': [{'id': b.id, 'product': p.name, 'club': club.name, 'quantity': float(b.quantity or 0), 'min_stock': float(b.min_stock or 0)} for b,p,club in rows]}

    async def _group_guests(request: Request, group_id: int):
        await _owner(request)
        try:
            payload = await langame_client.guests_search(groups=[group_id], size=100, page=1)
        except Exception as exc:
            return JSONResponse({'items': [], 'error': str(exc)}, status_code=502)
        if isinstance(payload, dict):
            items = payload.get('items') or payload.get('data') or payload.get('results') or payload.get('rows') or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        out = []
        for g in items:
            if not isinstance(g, dict):
                continue
            gid = g.get('id') or g.get('guest_id') or g.get('guestId')
            out.append({'fio': g.get('fio') or g.get('name') or g.get('full_name') or f'Гость #{gid}', 'langame_guest_id': gid, 'phone': g.get('phone')})
        return {'items': out}

    existing = {getattr(r, 'path', None) for r in app.routes}
    if '/api/work-center-v3/previous-shift' not in existing:
        app.add_api_route('/api/work-center-v3/previous-shift', _previous_shift, methods=['GET'])
    if '/api/work-center-v3/warehouse-categories' not in existing:
        app.add_api_route('/api/work-center-v3/warehouse-categories', _warehouse_categories, methods=['GET'])
    if '/api/work-center-v3/warehouse-category/{category_id}' not in existing:
        app.add_api_route('/api/work-center-v3/warehouse-category/{category_id}', _warehouse_category, methods=['GET'])
    if '/api/current-summary/langame-guests' not in existing:
        app.add_api_route('/api/current-summary/langame-guests', _group_guests, methods=['GET'])

    original = pc.compose_page
    if getattr(original, '_owner_hotfixed', False):
        return

    def compose_with_hotfix(html: str) -> str:
        result = original(html)
        result = result.replace('onclick="currentGroupGuests(${Number(g.id)})"', 'onclick="currentGroupGuests(${Number(g.id)}, \'${ownerEsc(g.name)}\')"')
        script = r'''<script>
(function(){
const _ownerEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const _money=v=>v==null?'—':Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const _back=()=>root.prepend(btn('← Рабочая зона',window.workCenter,'back'));
window.currentGroupGuests=async function(id,name){clear();setBottom(false);try{const d=await api('/api/current-summary/langame-guests?group_id='+Number(id));const items=d.items||[];root.innerHTML=`<section class="hero"><div class="eyebrow">ЛОЯЛЬНОСТЬ</div><div class="hero-title">${_ownerEsc(name||'Группа')}</div><div class="hero-sub">${items.length} гостей</div></section><div class="nav-card">${items.map(g=>`<section class="card"><div class="admin-name">${_ownerEsc(g.fio)}</div><div class="admin-meta">LANGAME #${_ownerEsc(g.langame_guest_id)}${g.phone?' · '+_ownerEsc(g.phone):''}</div></section>`).join('')||'<div class="empty">Гостей в этой группе нет</div>'}</div>`;_back()}catch(e){fail(e)}};
window.previousShift=async function(){clear();setBottom(false);try{const x=await api('/api/work-center-v3/previous-shift');const r=x.report;if(!r){root.innerHTML='<div class="empty">Предыдущей завершённой смены пока нет</div>';_back();return}return shiftReportOpen(Number(r.id))}catch(e){fail(e)}};
window.shiftReports=window.previousShift;
window.workFinance=async function(){clear();setBottom(false);root.innerHTML=`<section class="hero"><div class="eyebrow">ФИНАНСЫ КЛУБА</div><div class="hero-title">Выручка, расходы и прибыль</div></section><section class="card"><div class="row"><div class="row-main"><div class="row-title">От</div></div><input id="finFrom" type="date" value="${new Date().toLocaleDateString('sv-SE')}"></div><div class="row"><div class="row-main"><div class="row-title">До</div></div><input id="finTo" type="date" value="${new Date().toLocaleDateString('sv-SE')}"></div><button class="primary" onclick="loadFinance()">Показать период</button></section><div id="finOut"><div class="empty">Загрузка…</div></div>`;_back();await loadFinance()};
window.loadFinance=async function(){const f=document.getElementById('finFrom')?.value,t=document.getElementById('finTo')?.value;if(!f||!t)return;try{const d=await api('/api/work-center-v3/finance?date_from='+f+'&date_to='+t);document.getElementById('finOut').innerHTML=`<section class="card">${wcRow('Игровое время — выручка',_money(d.gaming))}${wcRow('Еда и услуги — выручка',_money(d.bar_sales))}${wcRow('Общая выручка',_money((d.gaming||0)+(d.bar_sales||0)))}${wcRow('Себестоимость проданных товаров',_money(d.bar_purchases))}${wcRow('Валовая прибыль',_money(d.bar_profit))}</section>`}catch(e){fail(e)}};
window.workWarehouse=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3/warehouse-categories');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Склад по категориям</div></section><div class="nav-card">${(d.categories||[]).map(c=>`<button class="nav-btn" onclick="warehouseCategory(${Number(c.id)}, '${_ownerEsc(c.name)}')"><span class="nav-icon">📦</span><span class="nav-copy"><span class="nav-label">${_ownerEsc(c.name)}</span><span class="nav-hint">${c.count} позиций</span></span><span class="nav-arrow">›</span></button>`).join('')||'<div class="empty">Категории склада не найдены</div>'}</div><button class="primary" onclick="criticalStock()">Критические остатки</button>`;_back()}catch(e){fail(e)}};
window.warehouseCategory=async function(id,name){clear();setBottom(false);try{const d=await api('/api/work-center-v3/warehouse-category/'+Number(id));root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД · КАТЕГОРИЯ</div><div class="hero-title">${_ownerEsc(name||'Товары')}</div></section><div class="nav-card">${(d.items||[]).map(x=>`<div class="row"><div class="row-main"><div class="row-title">${_ownerEsc(x.product)}</div><div class="row-sub">${_ownerEsc(x.club)}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')||'<div class="empty">В категории нет товаров</div>'}</div>`;_back()}catch(e){fail(e)}};
const oldWork=window.workCenter;window.workCenter=async function(){if(me?.role!=="owner")return oldWork?.();await oldWork?.();const cards=[...root.querySelectorAll('.nav-btn')];const b=cards.find(x=>x.textContent.includes('Предыдущая смена'));if(!b){const section=[...root.querySelectorAll('.section-title')].find(x=>x.textContent.includes('Смены и отчёты'));if(section){const n=section.nextElementSibling;if(n)n.innerHTML='<button class="nav-btn" onclick="previousShift()"><span class="nav-icon">📋</span><span class="nav-copy"><span class="nav-label">Предыдущая смена</span><span class="nav-hint">Последний завершённый отчёт</span></span><span class="nav-arrow">›</span></button>';}}};
})();</script>'''
        return result + script

    compose_with_hotfix._owner_hotfixed = True
    pc.compose_page = compose_with_hotfix

_install_sabot_owner_hotfix()

# Load the separately maintained critical-stock hotfix after the main owner patch.
try:
    from owner_critical_hotfix import install as _install_critical_stock_hotfix
    _install_critical_stock_hotfix()
    print('SAbot critical stock hotfix loaded', flush=True)
except Exception as exc:
    print(f'SAbot critical stock hotfix failed: {exc}', flush=True)
