from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SMMAccess(Base):
    """Dedicated SMM role/access layer."""
    __tablename__ = "smm_access"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    analytics_access: Mapped[str] = mapped_column(
        String(1000),
        default="social,guests,marketing,advertising",
        server_default="social,guests,marketing,advertising",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SMMTaskRate(Base):
    __tablename__ = "smm_task_rates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(50), default="шт", server_default="шт")
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SMMTask(Base):
    __tablename__ = "smm_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=1, server_default="1")
    unit: Mapped[str] = mapped_column(String(50), default="шт", server_default="шт")
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="submitted", server_default="submitted", index=True)
    proof: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
