from fastapi import Request
from sqlalchemy import select


def install():
    from app.webapp.app import app, current_user, owner_required
    from app.db.session import SessionLocal
    from app.models import InventoryBalance, Product, ProductCategory, Club
    import app.webapp.page_composer as pc

    async def owner(request: Request):
        user, _ = await current_user(request)
        owner_required(user)

    async def critical_categories(request: Request):
        await owner(request)
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(InventoryBalance, Product, Club, ProductCategory)
                .join(Product, Product.id == InventoryBalance.product_id)
                .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
                .join(Club, Club.id == InventoryBalance.club_id)
                .where(InventoryBalance.min_stock > 0, InventoryBalance.quantity <= InventoryBalance.min_stock)
                .order_by(ProductCategory.name, Product.name, Club.name)
            )).all()
        groups = {}
        for balance, product, club, category in rows:
            key = int(category.id) if category else 0
            name = category.name if category else 'Без категории'
            group = groups.setdefault(key, {'id': key, 'name': name, 'count': 0, 'items': []})
            group['count'] += 1
            group['items'].append({
                'product': product.name,
                'club': club.name,
                'quantity': float(balance.quantity or 0),
                'min_stock': float(balance.min_stock or 0),
            })
        return {'categories': list(groups.values())}

    if not any(getattr(r, 'path', None) == '/api/work-center-v3/critical-categories' for r in app.routes):
        app.add_api_route('/api/work-center-v3/critical-categories', critical_categories, methods=['GET'])

    original = pc.compose_page
    if getattr(original, '_critical_hotfixed', False):
        return

    def compose(html: str) -> str:
        result = original(html)
        script = r'''<script>
(function(){
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
window.criticalStock=async function(){clear();setBottom(false);try{const d=await api('/api/work-center-v3/critical-categories');root.innerHTML=`<section class="hero"><div class="eyebrow">СКЛАД</div><div class="hero-title">Критические остатки</div><div class="hero-sub">По категориям товаров</div></section>${(d.categories||[]).map(c=>`<section class="card"><div class="section-title">${esc(c.name)} <span class="muted">· ${c.count}</span></div>${c.items.map(x=>`<div class="row"><div class="row-main"><div class="row-title">${esc(x.product)}</div><div class="row-sub">${esc(x.club)} · минимум ${x.min_stock}</div></div><div class="row-value">${x.quantity}</div></div>`).join('')}</section>`).join('')||'<div class="empty">Критических остатков нет</div>'};root.prepend(btn('← Рабочая зона',window.workCenter,'back'))}catch(e){fail(e)}};
})();</script>'''
        return result + script
    compose._critical_hotfixed = True
    pc.compose_page = compose
