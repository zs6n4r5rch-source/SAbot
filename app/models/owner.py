from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    langame_guest_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    fio: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64), index=True)
    is_temp: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuestTelegram(Base):
    __tablename__ = "guest_telegram"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), unique=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    marketing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuestGroup(Base):
    __tablename__ = "guest_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    langame_group_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    percent: Mapped[int | None] = mapped_column(Integer)
    bonus_birthday: Mapped[bool | None] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuestGroupMember(Base):
    __tablename__ = "guest_group_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    guest_group_id: Mapped[int] = mapped_column(ForeignKey("guest_groups.id", ondelete="CASCADE"), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("guest_id", "guest_group_id"),)


class MarketingCampaign(Base):
    __tablename__ = "marketing_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft", index=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketingCampaignGroup(Base):
    __tablename__ = "marketing_campaign_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), index=True)
    guest_group_id: Mapped[int] = mapped_column(ForeignKey("guest_groups.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("campaign_id", "guest_group_id"),)


class MarketingRecipient(Base):
    __tablename__ = "marketing_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("campaign_id", "guest_id"),)


class OwnerDailyReportDelivery(Base):
    __tablename__ = "owner_daily_report_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="sending", server_default="sending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("report_date", "owner_telegram_id"),)


class OwnerReportSettings(Base):
    __tablename__ = "owner_report_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
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
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=utcnow)
