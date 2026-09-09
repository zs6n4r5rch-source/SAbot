from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    OwnerReportSettings,
    SalaryPayment,
    SalaryPeriod,
    Writeoff,
    WriteoffStatus,
)
from app.permissions import Permission, require_permission
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["unified-app-actions"])


async def actor(request: Request):
    return (await current_user(request))[0]


class ReportSettingsPatch(BaseModel):
    enabled: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    include_sales: bool | None = None
    include_shifts: bool | None = None
    include_inventory: bool | None = None
    include_discrepancies: bool | None = None
    include_salary: bool | None = None
    include_clients: bool | None = None
    send_excel: bool | None = None


@router.post("/warehouse/writeoffs/{writeoff_id}/approve")
async def approve_writeoff(writeoff_id: int, request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_WAREHOUSE)
    async with SessionLocal() as session:
        writeoff = await session.get(Writeoff, writeoff_id)
        if not writeoff:
            raise HTTPException(404, "Writeoff not found")
        if writeoff.status != WriteoffStatus.PENDING.value:
            raise HTTPException(409, f"Writeoff is already {writeoff.status}")
        writeoff.status = WriteoffStatus.APPROVED.value
        writeoff.approved_by = user.telegram_id
        writeoff.approved_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True, "id": writeoff_id, "status": WriteoffStatus.APPROVED.value}


@router.post("/warehouse/writeoffs/{writeoff_id}/reject")
async def reject_writeoff(writeoff_id: int, request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_WAREHOUSE)
    async with SessionLocal() as session:
        writeoff = await session.get(Writeoff, writeoff_id)
        if not writeoff:
            raise HTTPException(404, "Writeoff not found")
        if writeoff.status != WriteoffStatus.PENDING.value:
            raise HTTPException(409, f"Writeoff is already {writeoff.status}")
        writeoff.status = WriteoffStatus.REJECTED.value
        writeoff.approved_by = user.telegram_id
        writeoff.approved_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True, "id": writeoff_id, "status": WriteoffStatus.REJECTED.value}


@router.post("/salary/{period_id}/confirm")
async def confirm_salary(period_id: int, request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_FINANCE)
    async with SessionLocal() as session:
        period = await session.get(SalaryPeriod, period_id)
        if not period:
            raise HTTPException(404, "Salary period not found")
        if period.status == "paid":
            raise HTTPException(409, "Salary period is already paid")
        period.status = "confirmed"
        period.confirmed_by = user.telegram_id
        period.confirmed_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True, "id": period_id, "status": period.status}


@router.post("/salary/{period_id}/pay")
async def pay_salary(period_id: int, request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.MANAGE_FINANCE)
    async with SessionLocal() as session:
        period = await session.get(SalaryPeriod, period_id)
        if not period:
            raise HTTPException(404, "Salary period not found")
        if period.status != "confirmed":
            raise HTTPException(409, "Salary period must be confirmed before payment")
        existing = await session.scalar(select(SalaryPayment).where(SalaryPayment.salary_period_id == period_id))
        if existing:
            raise HTTPException(409, "Salary period is already paid")
        payment = SalaryPayment(
            salary_period_id=period.id,
            amount=period.total_amount,
            paid_by=user.telegram_id,
            paid_at=datetime.now(timezone.utc),
        )
        session.add(payment)
        period.status = "paid"
        await session.commit()
    return {"ok": True, "id": period_id, "status": "paid", "amount": float(period.total_amount or 0)}


@router.patch("/settings")
async def patch_settings(payload: ReportSettingsPatch, request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.READ_ALL)
    if user.role != "owner":
        raise HTTPException(403, "Owner role required")
    values: dict[str, Any] = payload.model_dump(exclude_none=True)
    async with SessionLocal() as session:
        row = await session.scalar(select(OwnerReportSettings).where(OwnerReportSettings.owner_telegram_id == user.telegram_id))
        if row is None:
            row = OwnerReportSettings(owner_telegram_id=user.telegram_id)
            session.add(row)
        mapping = {
            "timezone": "report_timezone", "hour": "report_hour", "minute": "report_minute",
            "enabled": "enabled", "include_sales": "include_sales", "include_shifts": "include_shifts",
            "include_inventory": "include_inventory", "include_discrepancies": "include_discrepancies",
            "include_salary": "include_salary", "include_clients": "include_clients", "send_excel": "send_excel",
        }
        for key, value in values.items():
            setattr(row, mapping[key], value)
        await session.commit()
    return {"ok": True, "settings": values}
