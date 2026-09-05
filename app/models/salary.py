from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShiftCloseReportStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class ShiftCloseReport(Base):
    __tablename__ = "shift_close_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"), unique=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=ShiftCloseReportStatus.PENDING.value, server_default=ShiftCloseReportStatus.PENDING.value, index=True)
    cash_expected: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cash_actual: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cash_difference: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cash_shortage_reason: Mapped[str | None] = mapped_column(String(100))
    cash_comment: Mapped[str | None] = mapped_column(Text)
    stock_items_count: Mapped[int | None] = mapped_column(Integer)
    stock_discrepancies_count: Mapped[int | None] = mapped_column(Integer)
    first_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleaning_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleaning_performed_by: Mapped[str | None] = mapped_column(String(255))
    cleaning_bonus_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("status IN ('pending','in_progress','submitted')", name="ck_shift_close_report_status"),)


class ShiftCloseStockItem(Base):
    __tablename__ = "shift_close_stock_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("shift_close_reports.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    langame_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    actual_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    difference: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    shortage_reason: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SalaryRule(Base):
    __tablename__ = "salary_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    rule_type: Mapped[str] = mapped_column(String(50))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SalaryPeriod(Base):
    __tablename__ = "salary_periods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    date_from: Mapped[Date] = mapped_column(Date)
    date_to: Mapped[Date] = mapped_column(Date)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("employee_id", "date_from", "date_to"),)


class SalaryAdjustment(Base):
    __tablename__ = "salary_adjustments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salary_period_id: Mapped[int] = mapped_column(ForeignKey("salary_periods.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NonMonetaryBonus(Base):
    __tablename__ = "non_monetary_bonuses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    bonus_type: Mapped[str] = mapped_column(String(50), default="review", server_default="review")
    title: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SalaryViolation(Base):
    __tablename__ = "salary_violations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual", index=True)
    source_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    premium_reduction_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    dismissal_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SalaryPayment(Base):
    __tablename__ = "salary_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salary_period_id: Mapped[int] = mapped_column(ForeignKey("salary_periods.id", ondelete="CASCADE"), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_by: Mapped[int] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(Text)
