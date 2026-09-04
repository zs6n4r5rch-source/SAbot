from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
    Text, UniqueConstraint, CheckConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    ADMIN = "admin"
    OWNER = "owner"
    SMM = "smm"


class ShiftStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class InventoryOperationType(StrEnum):
    ARRIVAL = "arrival"
    SALE = "sale"
    WRITEOFF = "writeoff"
    INVENTORY_ADJUSTMENT = "inventory_adjustment"
    MANUAL_ADJUSTMENT = "manual_adjustment"


class WriteoffStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InventoryStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DiscrepancyStatus(StrEnum):
    OPEN = "open"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RecipientStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Club(Base):
    __tablename__ = "clubs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    langame_club_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    langame_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class EmployeeClub(Base):
    __tablename__ = "employee_clubs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("employee_id", "club_id"),)


class TelegramUser(Base):
    __tablename__ = "telegram_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.ADMIN.value, server_default=UserRole.ADMIN.value)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("role IN ('admin', 'owner', 'smm')", name="ck_telegram_users_role"),)


class AccessProfile(Base):
    __tablename__ = "access_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    salary_per_shift: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cleaning_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ideal_close_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    cash_discipline_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    bar_bonus_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    employment_start_date: Mapped[Date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("role IN ('admin', 'owner', 'smm')", name="ck_access_profiles_role"),)


class TelegramBindingRequest(Base):
    __tablename__ = "telegram_binding_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("access_profiles.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_binding_requests_status"),
        Index("ix_binding_requests_pending_profile", "profile_id", "status"),
    )


class Shift(Base):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    langame_shift_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=ShiftStatus.OPEN.value, server_default=ShiftStatus.OPEN.value)
    system_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cash_difference: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cash_sales: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    card_sales: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    mobile_sales: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    refunds_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    refunds_card: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    collection: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    handover_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("status IN ('open', 'closed')", name="ck_shifts_status"),)


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


class SMMTask(Base):
    __tablename__ = "smm_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1, server_default="1")
    unit: Mapped[str] = mapped_column(String(50), default="шт", server_default="шт")
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="submitted", server_default="submitted", index=True)
    proof: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("status IN ('submitted','approved','rejected')", name="ck_smm_tasks_status"),)


class SalaryTaskRate(Base):
    __tablename__ = "salary_task_rates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(50), default="шт", server_default="шт")
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


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
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual", index=True)
    source_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    premium_reduction_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    dismissal_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
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


class AnalyticsDaily(Base):
    __tablename__ = "analytics_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    day: Mapped[Date] = mapped_column(Date, index=True)
    sales_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    sold_units: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, server_default="0")
    writeoff_units: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, server_default="0")
    discrepancy_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    shifts_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (UniqueConstraint("club_id", "day"),)


class AnalyticsProductDaily(Base):
    __tablename__ = "analytics_product_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    day: Mapped[Date] = mapped_column(Date, index=True)
    sold_units: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, server_default="0")
    sales_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    writeoff_units: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, server_default="0")
    __table_args__ = (UniqueConstraint("club_id", "product_id", "day"),)


class AnalyticsEmployeeDaily(Base):
    __tablename__ = "analytics_employee_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    day: Mapped[Date] = mapped_column(Date, index=True)
    shifts_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    sales_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    writeoff_units: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0, server_default="0")
    discrepancy_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    __table_args__ = (UniqueConstraint("club_id", "employee_id", "day"),)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[int] = mapped_column(primary_key=True)
    langame_guest_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    fio: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64), index=True)
    is_temp: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GuestGroup(Base):
    __tablename__ = "guest_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    langame_group_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    percent: Mapped[int | None] = mapped_column(Integer)
    bonus_birthday: Mapped[bool | None] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GuestGroupMember(Base):
    __tablename__ = "guest_group_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    guest_group_id: Mapped[int] = mapped_column(ForeignKey("guest_groups.id", ondelete="CASCADE"), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("guest_id", "guest_group_id"),)


class GuestTelegram(Base):
    __tablename__ = "guest_telegram"
    id: Mapped[int] = mapped_column(primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), unique=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    marketing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuestLinkToken(Base):
    __tablename__ = "guest_link_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketingCampaign(Base):
    __tablename__ = "marketing_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default=CampaignStatus.DRAFT.value, server_default=CampaignStatus.DRAFT.value, index=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('draft','scheduled','running','completed','cancelled')", name="ck_marketing_campaigns_status"),)


class MarketingCampaignGroup(Base):
    __tablename__ = "marketing_campaign_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), index=True)
    guest_group_id: Mapped[int] = mapped_column(ForeignKey("guest_groups.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("campaign_id", "guest_group_id"),)


class MarketingRecipient(Base):
    __tablename__ = "marketing_recipients"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default=RecipientStatus.PENDING.value, server_default=RecipientStatus.PENDING.value, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("campaign_id", "guest_id"),
        CheckConstraint("status IN ('pending','sent','failed')", name="ck_marketing_recipients_status"),
    )


class OwnerReportSettings(Base):
    __tablename__ = "owner_report_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    report_timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", server_default="Europe/Moscow")
    report_hour: Mapped[int] = mapped_column(Integer, default=9, server_default="9")
    report_minute: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    include_sales: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_shifts: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_inventory: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_discrepancies: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_salary: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_clients: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    send_excel: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OwnerDailyReportDelivery(Base):
    __tablename__ = "owner_daily_report_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[Date] = mapped_column(Date, index=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(20), default="sending", server_default="sending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("report_date", "owner_telegram_id"),)
