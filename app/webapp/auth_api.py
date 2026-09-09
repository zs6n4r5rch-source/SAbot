import json
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.models import AccessProfile, TelegramUser, UserRole
from app.webapp.app import validate_init_data
from app.db.session import SessionLocal

router = APIRouter(prefix="/api/app", tags=["auth"])

ROLE_LABELS = {
    UserRole.OWNER.value: "Владелец",
    UserRole.ADMIN.value: "Администратор",
    UserRole.SMM.value: "SMM-специалист",
    "guest": "Гость",
}

@router.get("/auth")
async def authorize(request: Request, role: str):
    pairs = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    try:
        raw_user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(401, "Invalid Telegram user data") from exc
    telegram_id = raw_user.get("id")
    if not telegram_id:
        raise HTTPException(401, "Telegram user is missing")
    username = str(raw_user.get("username") or "").lower().replace("@", "").strip()
    async with SessionLocal() as session:
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))).scalar_one_or_none()
        actual = user.role if user and user.active else None
        if actual is None and username:
            profile = (await session.execute(select(AccessProfile).where(AccessProfile.username == username, AccessProfile.active.is_(True), AccessProfile.role == UserRole.OWNER.value))).scalar_one_or_none()
            if profile:
                actual = UserRole.OWNER.value
                if user is None:
                    user = TelegramUser(telegram_id=telegram_id, role=actual, active=True)
                    session.add(user)
                    await session.commit()
        if role == "guest":
            return {"role": "guest", "actual_role": actual or "guest", "preview": False, "label": ROLE_LABELS["guest"]}
        if role not in ROLE_LABELS or actual != role:
            if actual == UserRole.OWNER.value and role in (UserRole.ADMIN.value, UserRole.SMM.value):
                return {"role": role, "actual_role": actual, "preview": True, "label": ROLE_LABELS[role]}
            raise HTTPException(403, "Для этого контура нет активной привязки владельца")
        return {"role": role, "actual_role": actual, "preview": False, "label": ROLE_LABELS[role]}
