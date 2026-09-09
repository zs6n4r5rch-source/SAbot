import secrets
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db.session import SessionLocal
from app.models import Guest, GuestLinkToken, GuestTelegram, UserRole
from app.services.audit import write_audit
from app.services.langame import LangameAPIError, langame_client
from app.webapp.app import current_user

router = APIRouter(prefix="/api/app", tags=["guest-invites"])
TOKEN_TTL = timedelta(days=7)
PAGE_SIZE = 100


def _rows_of(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


async def owner(request: Request):
    user, _ = await current_user(request)
    if user.role != UserRole.OWNER.value:
        raise HTTPException(403, "OWNER access required")
    return user


async def _bot_username() -> str:
    async with Bot(token=settings.telegram_bot_token) as bot:
        me = await bot.get_me()
    if not me.username:
        raise HTTPException(503, "Telegram bot username is not configured")
    return me.username


async def _load_all_langame_guests() -> list[dict]:
    result: list[dict] = []
    seen: set[int] = set()
    for page in range(1, 1001):
        try:
            payload = await langame_client.guests_search(page=page, size=PAGE_SIZE)
        except LangameAPIError as exc:
            raise HTTPException(502, f"LANGAME guests unavailable: {exc}") from exc
        rows = _rows_of(payload)
        if not rows:
            break
        new_rows = 0
        for row in rows:
            raw_id = row.get("guest_id", row.get("id"))
            try:
                guest_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if guest_id in seen:
                continue
            seen.add(guest_id)
            result.append(row)
            new_rows += 1
        if len(rows) < PAGE_SIZE or new_rows == 0:
            break
    return result


@router.post("/guest/invites/bulk")
async def create_bulk_guest_invites(request: Request):
    user = await owner(request)
    rows = await _load_all_langame_guests()
    if not rows:
        return {"ok": True, "total": 0, "created": 0, "reused": 0, "already_linked": 0, "items": []}

    bot_username = await _bot_username()
    now = datetime.now(timezone.utc)
    langame_ids: list[int] = []
    normalized: dict[int, dict] = {}
    for row in rows:
        try:
            gid = int(row.get("guest_id", row.get("id")))
        except (TypeError, ValueError):
            continue
        langame_ids.append(gid)
        normalized[gid] = row

    async with SessionLocal() as session:
        local_rows = (await session.execute(select(Guest).where(Guest.langame_guest_id.in_(langame_ids)))).scalars().all()
        local_by_remote = {int(g.langame_guest_id): g for g in local_rows}
        for gid in langame_ids:
            if gid in local_by_remote:
                continue
            data = normalized[gid]
            guest = Guest(
                langame_guest_id=gid,
                fio=data.get("fio") or data.get("name") or data.get("full_name"),
                phone=data.get("phone"),
                is_temp=bool(data.get("temp", data.get("is_temp", False))),
                is_virtual=False,
            )
            session.add(guest)
            local_by_remote[gid] = guest
        await session.flush()

        local_ids = [g.id for g in local_by_remote.values()]
        linked_rows = (await session.execute(select(GuestTelegram).where(GuestTelegram.guest_id.in_(local_ids)))).scalars().all()
        linked_ids = {row.guest_id for row in linked_rows}
        token_rows = (await session.execute(select(GuestLinkToken).where(GuestLinkToken.guest_id.in_(local_ids), GuestLinkToken.used_at.is_(None), GuestLinkToken.expires_at > now))).scalars().all()
        active_tokens = {row.guest_id: row for row in token_rows}

        items = []
        created = 0
        reused = 0
        already_linked = 0
        for gid in langame_ids:
            guest = local_by_remote[gid]
            if guest.id in linked_ids:
                already_linked += 1
                continue
            token_row = active_tokens.get(guest.id)
            if token_row is None:
                token_row = GuestLinkToken(
                    token=secrets.token_urlsafe(32),
                    guest_id=guest.id,
                    created_by=user.telegram_id,
                    expires_at=now + TOKEN_TTL,
                )
                session.add(token_row)
                await session.flush()
                active_tokens[guest.id] = token_row
                created += 1
            else:
                reused += 1
            items.append({
                "guest_id": gid,
                "local_guest_id": guest.id,
                "name": guest.fio or f"Гость #{gid}",
                "phone": guest.phone,
                "url": f"https://t.me/{bot_username}?start=guest_{token_row.token}",
                "expires_at": token_row.expires_at.isoformat(),
            })

        await session.commit()
        await write_audit(
            session,
            actor_telegram_id=user.telegram_id,
            action="guest_invites_bulk_created",
            entity_type="guest",
            payload={"total": len(langame_ids), "created": created, "reused": reused, "already_linked": already_linked},
        )

    return {"ok": True, "total": len(langame_ids), "created": created, "reused": reused, "already_linked": already_linked, "items": items}
