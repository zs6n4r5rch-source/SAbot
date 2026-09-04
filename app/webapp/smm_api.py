from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.models import TelegramUser, UserRole, Employee, Guest, MarketingCampaign, Shift
from app.models.smm import SMMAccess, SMMTask, SMMTaskRate
from app.webapp.app import current_user
from app.services.smm import get_smm_access, has_analytics

router = APIRouter()


def dec(v):
    return float(v or 0)


async def smm_context(request: Request):
    user, tg = await current_user(request)
    async with SessionLocal() as session:
        access = await get_smm_access(session, user.telegram_id)
    if not access:
        raise HTTPException(403, "SMM access required")
    return user, tg, access


class TaskCreate(BaseModel):
    task_type: str
    title: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0)
    proof: str | None = Field(default=None, max_length=4000)
    comment: str | None = Field(default=None, max_length=4000)


@router.get("/api/smm/me")
async def smm_me(request: Request):
    user, tg, access = await smm_context(request)
    async with SessionLocal() as session:
        employee = await session.get(Employee, access.employee_id) if access.employee_id else None
    return {"role": "smm", "telegram_id": user.telegram_id, "employee_id": access.employee_id, "display_name": employee.full_name if employee else tg.get("first_name", "SMM"), "analytics": sorted(x for x in access.analytics_access.split(",") if x)}


@router.get("/api/smm/analytics")
async def smm_analytics(request: Request, days: int = 30):
    user, _, access = await smm_context(request)
    if not has_analytics(access, "guests") and not has_analytics(access, "marketing") and not has_analytics(access, "advertising"):
        raise HTTPException(403, "Analytics access is restricted")
    days = min(max(days, 1), 365)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    async with SessionLocal() as session:
        guests = await session.scalar(select(func.count(Guest.id))) if has_analytics(access, "guests") else None
        campaigns = await session.scalar(select(func.count(MarketingCampaign.id)).where(MarketingCampaign.created_at >= start)) if has_analytics(access, "marketing") else None
        tasks = await session.scalar(select(func.count(SMMTask.id)).where(SMMTask.employee_id == access.employee_id, SMMTask.submitted_at >= start)) if access.employee_id else 0
        approved = await session.scalar(select(func.count(SMMTask.id)).where(SMMTask.employee_id == access.employee_id, SMMTask.status == "approved", SMMTask.submitted_at >= start)) if access.employee_id else 0
        earned = await session.scalar(select(func.coalesce(func.sum(SMMTask.quantity * SMMTask.unit_rate), 0)).where(SMMTask.employee_id == access.employee_id, SMMTask.status == "approved", SMMTask.submitted_at >= start)) if access.employee_id else 0
    return {"days": days, "guests": guests, "campaigns": campaigns, "tasks": tasks or 0, "approved_tasks": approved or 0, "earned": dec(earned)}


@router.get("/api/smm/tasks")
async def smm_tasks(request: Request, days: int = 30):
    user, _, access = await smm_context(request)
    if not access.employee_id: return {"items": []}
    start = datetime.now(timezone.utc) - timedelta(days=min(max(days, 1), 365))
    async with SessionLocal() as session:
        rows = (await session.execute(select(SMMTask).where(SMMTask.employee_id == access.employee_id, SMMTask.submitted_at >= start).order_by(SMMTask.submitted_at.desc()).limit(200))).scalars().all()
    return {"items": [{"id": x.id, "type": x.task_type, "title": x.title, "quantity": dec(x.quantity), "unit": x.unit, "rate": dec(x.unit_rate), "amount": dec(Decimal(x.quantity or 0) * Decimal(x.unit_rate or 0)), "status": x.status, "proof": x.proof, "submitted_at": x.submitted_at.isoformat()} for x in rows]}


@router.post("/api/smm/tasks")
async def smm_create_task(request: Request, payload: TaskCreate):
    user, _, access = await smm_context(request)
    if not access.employee_id: raise HTTPException(400, "SMM employee is not linked")
    async with SessionLocal() as session:
        rate = await session.scalar(select(SMMTaskRate).where(SMMTaskRate.task_type == payload.task_type, SMMTaskRate.active.is_(True)))
        if not rate: raise HTTPException(400, "Unknown or inactive task type")
        task = SMMTask(employee_id=access.employee_id, task_type=payload.task_type, title=payload.title, quantity=payload.quantity, unit=rate.unit, unit_rate=rate.rate, proof=payload.proof, comment=payload.comment)
        session.add(task); await session.commit(); await session.refresh(task)
        return {"ok": True, "id": task.id, "status": task.status, "amount": dec(Decimal(task.quantity) * Decimal(task.unit_rate))}


@router.get("/api/smm/tasks/pending")
async def smm_pending(request: Request):
    user, _, _ = await smm_context(request)
    if user.role != UserRole.OWNER.value: raise HTTPException(403, "OWNER access required")
    async with SessionLocal() as session:
        rows = (await session.execute(select(SMMTask, Employee).join(Employee, Employee.id == SMMTask.employee_id).where(SMMTask.status == "submitted").order_by(SMMTask.submitted_at))).all()
    return {"items": [{"id": t.id, "employee": e.full_name, "title": t.title, "type": t.task_type, "quantity": dec(t.quantity), "rate": dec(t.unit_rate), "amount": dec(Decimal(t.quantity) * Decimal(t.unit_rate)), "proof": t.proof, "submitted_at": t.submitted_at.isoformat()} for t,e in rows]}


@router.post("/api/smm/tasks/{task_id}/{action}")
async def smm_review_task(task_id: int, action: str, request: Request):
    user, _, _ = await smm_context(request)
    if user.role != UserRole.OWNER.value: raise HTTPException(403, "OWNER access required")
    if action not in ("approve", "reject"): raise HTTPException(400, "Unknown action")
    async with SessionLocal() as session:
        task = await session.get(SMMTask, task_id)
        if not task: raise HTTPException(404, "Task not found")
        if task.status != "submitted": raise HTTPException(400, "Task is already reviewed")
        task.status = "approved" if action == "approve" else "rejected"
        task.approved_by = user.telegram_id; task.approved_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True, "status": task.status}
