from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.bot.penalties import RULE_MAP, create_manual_penalty
from app.db.session import SessionLocal
from app.models import Employee, SalaryViolation
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app/penalties", tags=["penalties"])


class ManualPenaltyIn(BaseModel):
    employee_id: int
    rule_code: str
    comment: str = Field(min_length=1, max_length=4000)


async def owner_user(request: Request):
    user = (await current_user(request))[0]
    if user.role != "owner":
        raise HTTPException(403, "Penalty management is restricted to owner")
    return user


@router.get("")
async def penalty_list(request: Request):
    await owner_user(request)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(SalaryViolation, Employee)
                .join(Employee, Employee.id == SalaryViolation.employee_id)
                .order_by(desc(SalaryViolation.created_at))
                .limit(200)
            )
        ).all()
    return {
        "items": [
            {
                "id": v.id,
                "employee": e.full_name,
                "employee_id": v.employee_id,
                "shift_id": v.shift_id,
                "type": v.rule_code,
                "title": v.title,
                "amount": float(Decimal(str(v.amount or 0))),
                "source": v.source,
                "comment": v.comment,
                "created_at": v.created_at.isoformat(),
            }
            for v, e in rows
        ],
        "rules": [
            {"code": code, "title": title, "amount": float(amount)}
            for code, (code, title, amount) in RULE_MAP.items()
        ],
    }


@router.post("")
async def add_penalty(payload: ManualPenaltyIn, request: Request):
    user = await owner_user(request)
    if payload.rule_code not in RULE_MAP:
        raise HTTPException(400, "Unknown penalty rule")
    try:
        await create_manual_penalty(user.telegram_id, payload.employee_id, payload.rule_code, payload.comment)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}
