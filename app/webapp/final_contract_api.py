from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.db.session import SessionLocal
from app.models import (
    CampaignStatus,
    Employee,
    Guest,
    GuestGroupMember,
    GuestTelegram,
    MarketingCampaign,
    MarketingCampaignGroup,
    MarketingRecipient,
    RecipientStatus,
    SalaryPayment,
    SalaryPeriod,
    SalaryViolation,
    Shift,
    ShiftCloseReport,
)
from app.permissions import Permission, require_permission
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["final-contract"])


def rows_of(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


async def actor(request: Request):
    return (await current_user(request))[0]


def allow_crm(user, *, smm=False):
    if user.role == "owner":
        return
    if user.role == "admin":
        require_permission(user.role, Permission.GUESTS)
        return
    if smm and user.role == "smm":
        require_permission(user.role, Permission.AUDIENCE)
        return
    raise HTTPException(403, "CRM access is not available for this role")


@router.get("/crm")
async def final_crm(request: Request, q: str = ""):
    user = await actor(request)
    allow_crm(user, smm=True)
    try:
        return {"source": "langame", "items": rows_of(await langame_client.guests_search(query=q or None, size=100))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME CRM unavailable: {exc}") from exc


@router.get("/crm/groups")
async def final_crm_groups(request: Request):
    user = await actor(request)
    allow_crm(user, smm=True)
    try:
        groups = rows_of(await langame_client.guest_groups())
        return {"source": "langame", "items": [{"id": g.get("id", g.get("group_id", g.get("guest_group_id"))), "name": g.get("name") or g.get("title") or "Без названия", "count": g.get("count", g.get("guests_count"))} for g in groups]}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME groups unavailable: {exc}") from exc


@router.get("/crm/groups/{group_id}/guests")
async def final_crm_group_guests(group_id: int, request: Request):
    user = await actor(request)
    allow_crm(user, smm=True)
    try:
        return {"source": "langame", "group_id": group_id, "items": rows_of(await langame_client.guests_search(groups=[group_id], size=100))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc


@router.get("/crm/guests/{guest_id}")
async def final_crm_guest(guest_id: int, request: Request):
    user = await actor(request)
    allow_crm(user, smm=True)
    try:
        guest_rows = rows_of(await langame_client.guest_by_id(guest_id))
        guest = guest_rows[0] if guest_rows else None
        if user.role == "smm":
            return {"source": "langame", "guest": guest, "sessions": None, "privacy": "marketing_contour"}
        return {"source": "langame", "guest": guest, "sessions": rows_of(await langame_client.guest_sessions(guest_id=guest_id, page_limit=500))}
    except LangameAPIError as exc:
        raise HTTPException(502, f"LANGAME guest unavailable: {exc}") from exc


@router.get("/crm/local-links")
async def final_crm_local_links(request: Request):
    user = await actor(request)
    allow_crm(user, smm=True)
    async with SessionLocal() as session:
        rows = (await session.execute(select(GuestTelegram, Guest))).all()
    return {"items": [{"guest_id": g.id, "name": g.fio, "phone": g.phone, "telegram_user_id": t.telegram_user_id, "marketing_consent": t.marketing_consent, "linked_at": t.linked_at.isoformat() if t.linked_at else None} for t, g in rows]}


@router.get("/shifts")
async def final_shifts(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        stmt = select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id)
        if user.role == "admin":
            stmt = stmt.where(Shift.employee_id == user.employee_id)
        rows = (await session.execute(stmt.order_by(desc(Shift.started_at)).limit(100))).all()
    return {"items": [{"id": s.id, "langame_shift_id": s.langame_shift_id, "employee": e.full_name if e else None, "employee_id": s.employee_id, "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None, "status": s.status, "system_cash": float(s.system_cash or 0), "actual_cash": float(s.actual_cash or 0), "cash_difference": float(s.cash_difference or 0), "cash_sales": float(s.cash_sales or 0), "card_sales": float(s.card_sales or 0), "mobile_sales": float(s.mobile_sales or 0), "collection": float(s.collection or 0), "handover_note": s.handover_note} for s, e in rows]}


@router.get("/shifts/previous")
async def final_previous_shift(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        stmt = select(Shift, Employee).outerjoin(Employee, Employee.id == Shift.employee_id).where(Shift.ended_at.is_not(None))
        if user.role == "admin":
            stmt = stmt.where(Shift.employee_id == user.employee_id)
        row = (await session.execute(stmt.order_by(desc(Shift.ended_at)).limit(1))).first()
    if not row:
        return {"item": None}
    s, e = row
    return {"item": {"id": s.id, "langame_shift_id": s.langame_shift_id, "employee": e.full_name if e else None, "employee_id": s.employee_id, "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat(), "system_cash": float(s.system_cash or 0), "actual_cash": float(s.actual_cash or 0), "cash_difference": float(s.cash_difference or 0), "cash_sales": float(s.cash_sales or 0), "card_sales": float(s.card_sales or 0), "mobile_sales": float(s.mobile_sales or 0), "collection": float(s.collection or 0), "handover_note": s.handover_note}}


@router.get("/shifts/close-reports")
async def final_close_reports(request: Request, limit: int = 100):
    user = await actor(request)
    require_permission(user.role, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        stmt = select(ShiftCloseReport)
        if user.role == "admin":
            stmt = stmt.where(ShiftCloseReport.employee_id == user.employee_id)
        rows = (await session.execute(stmt.order_by(desc(ShiftCloseReport.created_at)).limit(min(max(limit, 1), 200)))).scalars().all()
    return {"items": [{"id": r.id, "shift_id": r.shift_id, "employee_id": r.employee_id, "status": r.status, "cash_expected": float(r.cash_expected or 0), "cash_actual": float(r.cash_actual or 0), "cash_difference": float(r.cash_difference or 0), "cash_shortage_reason": r.cash_shortage_reason, "cash_comment": r.cash_comment, "stock_items_count": r.stock_items_count, "stock_discrepancies_count": r.stock_discrepancies_count, "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None, "cleaning_confirmed_at": r.cleaning_confirmed_at.isoformat() if r.cleaning_confirmed_at else None, "cleaning_performed_by": r.cleaning_performed_by, "cleaning_bonus_amount": float(r.cleaning_bonus_amount or 0)} for r in rows]}


@router.get("/penalties")
async def final_penalties(request: Request):
    user = await actor(request)
    if user.role == "owner":
        pass
    elif user.role == "admin":
        require_permission(user.role, Permission.OWN_PENALTIES)
    else:
        raise HTTPException(403, "Penalties are not available for this role")
    async with SessionLocal() as session:
        stmt = select(SalaryViolation, Employee).join(Employee, Employee.id == SalaryViolation.employee_id)
        if user.role == "admin":
            stmt = stmt.where(SalaryViolation.employee_id == user.employee_id)
        rows = (await session.execute(stmt.order_by(desc(SalaryViolation.created_at)).limit(200))).all()
    return {"source": "SAbot NEW/local", "items": [{"id": v.id, "employee": e.full_name, "employee_id": v.employee_id, "shift_id": v.shift_id, "type": v.rule_code, "title": v.title, "amount": float(v.amount or 0), "premium_reduction_percent": float(v.premium_reduction_percent or 0), "dismissal_required": bool(v.dismissal_required), "comment": v.comment, "status": "charged", "created_at": v.created_at.isoformat()} for v, e in rows]}


@router.get("/salary")
async def final_salary(request: Request, limit: int = 100):
    user = await actor(request)
    require_permission(user.role, Permission.READ_ALL if user.role == "owner" else Permission.SHIFT)
    async with SessionLocal() as session:
        stmt = select(SalaryPeriod, Employee).join(Employee, Employee.id == SalaryPeriod.employee_id)
        if user.role == "admin":
            stmt = stmt.where(SalaryPeriod.employee_id == user.employee_id)
        rows = (await session.execute(stmt.order_by(desc(SalaryPeriod.date_to)).limit(min(max(limit, 1), 300)))).all()
        result = []
        for p, e in rows:
            payment = await session.scalar(select(SalaryPayment).where(SalaryPayment.salary_period_id == p.id))
            result.append({"id": p.id, "employee_id": p.employee_id, "employee": e.full_name, "date_from": p.date_from.isoformat(), "date_to": p.date_to.isoformat(), "base_amount": float(p.base_amount or 0), "bonus_amount": float(p.bonus_amount or 0), "total_amount": float(p.total_amount or 0), "status": p.status, "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None, "paid": bool(payment), "paid_at": payment.paid_at.isoformat() if payment else None, "paid_amount": float(payment.amount or 0) if payment else None})
    return {"items": result}


@router.get("/guest/me")
async def final_guest_me(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.OWN_PROFILE)
    async with SessionLocal() as session:
        link = (await session.execute(select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).where(GuestTelegram.telegram_user_id == user.telegram_id))).first()
    if not link:
        raise HTTPException(404, "Guest profile is not linked")
    tg, guest = link
    balance = bonuses = history = None
    try:
        rows = rows_of(await langame_client.guest_by_id(int(guest.langame_guest_id)))
        if rows:
            data = rows[0]
            balance = data.get("balance")
            bonuses = data.get("bonus_balance", data.get("bonuses"))
        history = rows_of(await langame_client.guest_sessions(guest_id=int(guest.langame_guest_id), page_limit=100))
    except LangameAPIError:
        pass
    return {"id": guest.id, "name": guest.fio, "phone": guest.phone, "marketing_consent": tg.marketing_consent, "marketing_consent_at": tg.marketing_consent_at.isoformat() if tg.marketing_consent_at else None, "balance": balance, "bonuses": bonuses, "history": history, "source_note": "Guest data is resolved from the authenticated Telegram link; LANGAME remains read-only."}


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=4096)
    group_id: int | None = None
    all_consent: bool = False
    scheduled_at: datetime | None = None


class CampaignSchedule(BaseModel):
    scheduled_at: datetime


async def campaign_access(request: Request):
    user = await actor(request)
    require_permission(user.role, Permission.CAMPAIGNS)
    return user


@router.get("/smm/campaigns")
async def final_campaigns(request: Request):
    await campaign_access(request)
    async with SessionLocal() as session:
        rows = (await session.execute(select(MarketingCampaign).order_by(desc(MarketingCampaign.created_at)).limit(100))).scalars().all()
        result = []
        for campaign in rows:
            recipients = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign.id)) or 0
            sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign.id, MarketingRecipient.status == RecipientStatus.SENT.value)) or 0
            result.append({"id": campaign.id, "name": campaign.name, "message": campaign.message, "status": campaign.status, "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None, "created_at": campaign.created_at.isoformat(), "recipients": recipients, "sent": sent, "confirmed_at": campaign.confirmed_at.isoformat() if campaign.confirmed_at else None})
    return {"source": "SAbot local", "items": result, "delivery": "READY"}


@router.post("/smm/campaigns")
async def create_campaign(payload: CampaignCreate, request: Request):
    user = await campaign_access(request)
    if payload.group_id is None and not payload.all_consent:
        raise HTTPException(422, "Specify group_id or all_consent=true")
    async with SessionLocal() as session:
        campaign = MarketingCampaign(name=payload.name, message=payload.message, created_by=user.telegram_id, status=CampaignStatus.DRAFT.value)
        session.add(campaign)
        await session.flush()
        if payload.group_id is not None:
            session.add(MarketingCampaignGroup(campaign_id=campaign.id, guest_group_id=payload.group_id))
            query = select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).join(GuestGroupMember, GuestGroupMember.guest_id == Guest.id).where(GuestGroupMember.guest_group_id == payload.group_id, GuestTelegram.marketing_consent.is_(True))
        else:
            query = select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).where(GuestTelegram.marketing_consent.is_(True))
        recipients = (await session.execute(query)).all()
        for link, guest in recipients:
            session.add(MarketingRecipient(campaign_id=campaign.id, guest_id=guest.id, telegram_chat_id=link.telegram_chat_id))
        if payload.scheduled_at:
            campaign.scheduled_at = payload.scheduled_at.astimezone(timezone.utc) if payload.scheduled_at.tzinfo else payload.scheduled_at.replace(tzinfo=timezone.utc)
            campaign.status = CampaignStatus.SCHEDULED.value
        await session.commit()
    return {"ok": True, "id": campaign.id, "status": campaign.status, "recipients": len(recipients)}


@router.post("/smm/campaigns/{campaign_id}/schedule")
async def schedule_campaign(campaign_id: int, payload: CampaignSchedule, request: Request):
    await campaign_access(request)
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        count = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign_id)) or 0
        if not count:
            raise HTTPException(409, "Campaign has no consented recipients")
        campaign.scheduled_at = payload.scheduled_at.astimezone(timezone.utc) if payload.scheduled_at.tzinfo else payload.scheduled_at.replace(tzinfo=timezone.utc)
        campaign.status = CampaignStatus.SCHEDULED.value
        await session.commit()
    return {"ok": True, "id": campaign_id, "status": CampaignStatus.SCHEDULED.value}


@router.post("/smm/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: int, request: Request):
    user = await campaign_access(request)
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if not campaign or campaign.status not in {CampaignStatus.DRAFT.value, CampaignStatus.SCHEDULED.value}:
            raise HTTPException(409, "Campaign is not sendable")
        count = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign_id, MarketingRecipient.status == RecipientStatus.PENDING.value)) or 0
        if not count:
            raise HTTPException(409, "Campaign has no pending recipients")
        campaign.status = CampaignStatus.RUNNING.value
        campaign.confirmed_by = user.telegram_id
        campaign.confirmed_at = datetime.now(timezone.utc)
        await session.commit()
    from aiogram import Bot
    from app.bot.mailing import _send_campaign
    from app.config import settings
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await _send_campaign(bot, campaign_id, user.telegram_id)
    finally:
        await bot.session.close()
    return {"ok": True, "id": campaign_id, "status": "completed"}
