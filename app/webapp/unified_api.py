from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import Employee, InventoryBalance, Product, ProductCategory, Shift, UserRole, Guest, GuestTelegram, GuestGroupMember, SalaryViolation, MarketingCampaign
from app.permissions import Permission, require_permission
from app.services.langame import langame_client, LangameAPIError
from app.services.timezone_policy import local_day_bounds, timezone_name
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["unified-app"])

def num(value: Any) -> float:
    try: return float(Decimal(str(value or 0)))
    except Exception: return 0.0

def rows_of(payload: Any) -> list[dict]:
    if isinstance(payload, list): return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict): return []
    for key in ("data", "items", "results", "rows"):
        if isinstance(payload.get(key), list): return [x for x in payload[key] if isinstance(x, dict)]
    return []

def label(obj: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        if obj.get(key) not in (None, ""): return str(obj[key])
    return default

async def user_for(request: Request): return (await current_user(request))[0]
def need(user, permission): require_permission(user.role, permission)

async def sales_rows(start: datetime, end: datetime) -> list[dict]:
    result=[]; page=1
    while page <= 100:
        payload=await langame_client.product_sales(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'), page=page, page_limit=500)
        batch=rows_of(payload)
        if not batch: break
        result.extend(batch)
        total_pages=payload.get('total_pages') if isinstance(payload,dict) else None
        if total_pages is None or page >= int(total_pages): break
        page += 1
    return result

async def product_sales_totals(start, end):
    revenue=Decimal('0'); units=Decimal('0')
    for row in await sales_rows(start,end):
        if int(row.get('cancel',0) or 0)==1: continue
        qty=Decimal(str(row.get('count',row.get('quantity',0)) or 0)); price=Decimal(str(row.get('price_sale',row.get('price',0)) or 0))
        units += qty; revenue += qty*price
    return float(revenue), float(units)

@router.get('/overview')
async def overview(request: Request):
    user=await user_for(request); start, now=local_day_bounds(); product_revenue=product_units=0.0; langame_status='ok'
    try: product_revenue, product_units=await product_sales_totals(start,now)
    except LangameAPIError: langame_status='unavailable'
    async with SessionLocal() as session:
        critical=await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock>0,InventoryBalance.quantity<=InventoryBalance.min_stock)) or 0
        guests=await session.scalar(select(func.count(Guest.id))) or 0
    return {'role':user.role,'timezone':timezone_name(),'revenue':{'products':product_revenue,'gaming':None,'other':None,'total':product_revenue,'product_units':product_units},'attention':[{'key':'critical_stock','count':critical,'title':'Критический склад','target':'warehouse'}] if critical else [],'kpi':{'guests':guests,'new_guests':None,'average_check':None},'source_status':{'langame':langame_status}}

@router.get('/summary')
async def summary_alias(request: Request): return await overview(request)

@router.get('/work-center')
async def work_center(request: Request):
    user=await user_for(request); need(user, Permission.SHIFT if user.role=='admin' else Permission.READ_ALL)
    async with SessionLocal() as session:
        open_shifts=await session.scalar(select(func.count(Shift.id)).where(Shift.ended_at.is_(None))) or 0
        critical=await session.scalar(select(func.count(InventoryBalance.id)).where(InventoryBalance.min_stock>0,InventoryBalance.quantity<=InventoryBalance.min_stock)) or 0
    return {'role':user.role,'sections':['hall','guests','finance','warehouse','previous_shift','control'],'open_shifts':open_shifts,'critical_stock':critical}

@router.get('/crm')
async def crm(request: Request, q: str=''):
    user=await user_for(request); need(user, Permission.MANAGE_CRM if user.role=='owner' else Permission.GUESTS)
    try: return {'source':'langame','items':rows_of(await langame_client.guests_search(query=q or None,size=100))}
    except LangameAPIError as exc: raise HTTPException(502,f'LANGAME CRM unavailable: {exc}') from exc

@router.get('/crm/groups')
async def crm_groups(request: Request):
    user=await user_for(request); need(user, Permission.MANAGE_CRM if user.role=='owner' else Permission.GUESTS)
    try: return {'source':'langame','items':[{'id':g.get('id',g.get('group_id',g.get('guest_group_id'))),'name':label(g,'name','title',default='Без названия'),'count':g.get('count',g.get('guests_count'))} for g in rows_of(await langame_client.guest_groups())]}
    except LangameAPIError as exc: raise HTTPException(502,f'LANGAME groups unavailable: {exc}') from exc

@router.get('/crm/groups/{group_id}')
async def crm_group(group_id:int, request:Request):
    data=await crm_groups(request); item=next((x for x in data['items'] if x['id']==group_id),None)
    if not item: raise HTTPException(404,'Group not found')
    return item

@router.get('/crm/groups/{group_id}/guests')
async def crm_group_guests(group_id:int,request:Request):
    user=await user_for(request); need(user, Permission.MANAGE_CRM if user.role=='owner' else Permission.GUESTS)
    try:return {'source':'langame','group_id':group_id,'items':rows_of(await langame_client.guests_search(groups=[group_id],size=100))}
    except LangameAPIError as exc: raise HTTPException(502,f'LANGAME guests unavailable: {exc}') from exc

@router.get('/crm/guests/{guest_id}')
async def crm_guest(guest_id:int,request:Request):
    user=await user_for(request); need(user, Permission.MANAGE_CRM if user.role=='owner' else Permission.GUESTS)
    try:
        payload=await langame_client.guest_by_id(guest_id); rows=rows_of(payload); guest=rows[0] if rows else None
        return {'source':'langame','guest':guest,'sessions':rows_of(await langame_client.guest_sessions(guest_id=guest_id,page_limit=500))}
    except LangameAPIError as exc: raise HTTPException(502,f'LANGAME guest unavailable: {exc}') from exc

@router.get('/warehouse')
async def warehouse(request:Request):
    user=await user_for(request); need(user, Permission.MANAGE_WAREHOUSE if user.role=='owner' else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows=(await session.execute(select(InventoryBalance,Product,ProductCategory).join(Product,Product.id==InventoryBalance.product_id).outerjoin(ProductCategory,ProductCategory.id==Product.category_id))).all()
    return {'source':'local_control_layer','items':[{'id':b.id,'product':p.name,'category':c.name if c else 'Other','quantity':num(b.quantity),'min_stock':num(b.min_stock),'critical':bool(b.min_stock>0 and b.quantity<=b.min_stock)} for b,p,c in rows]}

@router.get('/warehouse/categories')
async def warehouse_categories(request:Request):
    user=await user_for(request); need(user, Permission.MANAGE_WAREHOUSE if user.role=='owner' else Permission.WAREHOUSE)
    async with SessionLocal() as session:
        rows=(await session.execute(select(ProductCategory).where(ProductCategory.active.is_(True)).order_by(ProductCategory.name))).scalars().all()
    return {'items':[{'id':x.id,'name':x.name} for x in rows]}

@router.get('/warehouse/critical')
async def warehouse_critical(request:Request):
    data=await warehouse(request); return {'items':[x for x in data['items'] if x['critical']]}

@router.get('/warehouse/sales')
async def warehouse_sales(request:Request,days:int=30):
    user=await user_for(request); need(user, Permission.MANAGE_WAREHOUSE if user.role=='owner' else Permission.SALES)
    end=datetime.now(timezone.utc); start=end-timedelta(days=min(max(days,1),365)); return {'items':await sales_rows(start,end),'days':days,'source':'langame'}

@router.get('/finance')
async def unified_finance(request:Request,days:int=30):
    user=await user_for(request); need(user,Permission.MANAGE_FINANCE); days=min(max(days,1),365); end=datetime.now(timezone.utc); start=end-timedelta(days=days); revenue,units=await product_sales_totals(start,end)
    return {'days':days,'revenue':{'gaming':None,'products':revenue,'other':None,'total':revenue},'products':{'units':units,'revenue':revenue,'cogs':None,'profit':None,'margin':None},'source_note':'COGS/gaming/other остаются unavailable до подтверждения полей источника.'}

@router.get('/shifts')
async def shifts(request:Request):
    user=await user_for(request); need(user,Permission.READ_ALL if user.role=='owner' else Permission.SHIFT)
    async with SessionLocal() as session:
        rows=(await session.execute(select(Shift,Employee).outerjoin(Employee,Employee.id==Shift.employee_id).order_by(desc(Shift.started_at)).limit(100))).all()
    return {'items':[{'id':s.id,'employee':e.full_name if e else None,'started_at':s.started_at.isoformat(),'ended_at':s.ended_at.isoformat() if s.ended_at else None,'status':s.status} for s,e in rows]}

@router.get('/shifts/previous')
async def previous_shift(request:Request):
    user=await user_for(request); need(user,Permission.READ_ALL if user.role=='owner' else Permission.SHIFT)
    async with SessionLocal() as session: row=(await session.execute(select(Shift,Employee).outerjoin(Employee,Employee.id==Shift.employee_id).where(Shift.ended_at.is_not(None)).order_by(desc(Shift.ended_at)).limit(1))).first()
    if not row:return {'item':None}
    s,e=row; return {'item':{'id':s.id,'employee':e.full_name if e else None,'started_at':s.started_at.isoformat(),'ended_at':s.ended_at.isoformat(),'cash_difference':num(s.cash_difference)}}

@router.get('/penalties')
async def penalties(request:Request):
    user=await user_for(request)
    async with SessionLocal() as session:
        stmt=select(SalaryViolation,Employee).join(Employee,Employee.id==SalaryViolation.employee_id).order_by(desc(SalaryViolation.created_at))
        if user.role=='admin' and user.employee_id: stmt=stmt.where(SalaryViolation.employee_id==user.employee_id)
        elif user.role!='owner': need(user,Permission.OWN_PENALTIES)
        rows=(await session.execute(stmt.limit(200))).all()
    return {'source':'SAbot NEW/local','items':[{'id':v.id,'employee':e.full_name,'type':v.rule_code,'title':v.title,'amount':num(v.amount),'status':'charged','created_at':v.created_at.isoformat()} for v,e in rows]}

@router.get('/analytics')
async def unified_analytics(request:Request,days:int=30):
    user=await user_for(request); need(user,Permission.READ_ALL); days=min(max(days,1),365); end=datetime.now(timezone.utc); start=end-timedelta(days=days); revenue,units=await product_sales_totals(start,end)
    return {'days':days,'kpi':{'product_revenue':revenue,'product_units':units},'comparison':{'occupancy':None,'revenue_per_hour':None,'revenue_per_pc':None,'arpu':None,'retention':None},'note':'Unavailable metrics remain NULL until their source is verified.'}

@router.get('/admin/me')
async def admin_me(request:Request):
    user=await user_for(request); need(user,Permission.SHIFT); return {'employee_id':user.employee_id,'permissions':sorted(p.value for p in __import__('app.permissions',fromlist=['ROLE_PERMISSIONS']).ROLE_PERMISSIONS['admin'])}

@router.get('/smm/campaigns')
async def smm_campaigns(request:Request):
    user=await user_for(request); need(user,Permission.CAMPAIGNS)
    async with SessionLocal() as session: rows=(await session.execute(select(MarketingCampaign).order_by(desc(MarketingCampaign.created_at)).limit(100))).scalars().all()
    return {'source':'SAbot local','items':[{'id':x.id,'name':x.name,'status':x.status,'scheduled_at':x.scheduled_at.isoformat() if x.scheduled_at else None} for x in rows],'delivery':'TO VERIFY'}

@router.get('/guest/me')
async def guest_me(request:Request):
    user=await user_for(request); need(user,Permission.OWN_PROFILE)
    async with SessionLocal() as session:
        link=(await session.execute(select(GuestTelegram,Guest).join(Guest,Guest.id==GuestTelegram.guest_id).where(GuestTelegram.telegram_user_id==user.telegram_id))).first()
    if not link: raise HTTPException(404,'Guest profile is not linked')
    _,guest=link; return {'id':guest.id,'name':guest.fio,'phone':guest.phone,'balance':None,'bonuses':None,'history':None,'source_note':'Only linked local identity is exposed; unverified fields are unavailable.'}
