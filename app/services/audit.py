import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog

async def write_audit(
    session: AsyncSession,
    *,
    actor_telegram_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    payload: dict | None = None,
    actor_employee_id: int | None = None,
) -> None:
    session.add(AuditLog(
        actor_telegram_id=actor_telegram_id,
        actor_employee_id=actor_employee_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
    ))
    await session.commit()
