import asyncio
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.bot.keyboards import mailing_menu
from app.db.session import SessionLocal
from app.models import (
    Guest, GuestGroup, GuestGroupMember, GuestTelegram, MarketingCampaign,
    MarketingCampaignGroup, MarketingRecipient, RecipientStatus, CampaignStatus,
    TelegramUser, UserRole,
)
from app.services.audit import write_audit

router = Router()


class MailingState(StatesGroup):
    waiting_name = State()
    waiting_message = State()


async def is_owner(message: Message) -> bool:
    if not message.from_user:
        return False
    async with SessionLocal() as session:
        result = await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        return bool(user and user.active and user.role == UserRole.OWNER.value)


def audience_keyboard(groups: list[GuestGroup]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🏷 {g.name}", callback_data=f"mail_group:{g.id}")] for g in groups]
    rows.append([InlineKeyboardButton(text="👥 Все с согласием", callback_data="mail_all")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mail_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def campaign_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Проверить snapshot", callback_data=f"mail_snapshot:{campaign_id}")],
        [InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data=f"mail_send:{campaign_id}")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"mail_cancel_campaign:{campaign_id}")],
    ])


async def create_campaign(message: Message, state: FSMContext):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await state.clear()
    await state.set_state(MailingState.waiting_name)
    await message.answer("📣 Новая рассылка\n\nВведите название кампании.\nДля отмены: /cancel")


@router.message(F.text == "📣 Рассылки")
async def mailings(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца.")
        return
    await message.answer("📣 Рассылки\nОтправка выполняется только по локальным Telegram-привязкам и только при marketing_consent=true.", reply_markup=mailing_menu())


@router.message(F.text == "➕ Новая рассылка")
async def new_mailing(message: Message, state: FSMContext):
    await create_campaign(message, state)


@router.message(MailingState.waiting_name)
async def mailing_name(message: Message, state: FSMContext):
    if not await is_owner(message):
        await state.clear(); return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название.")
        return
    await state.update_data(name=name[:255])
    await state.set_state(MailingState.waiting_message)
    await message.answer("Теперь отправьте текст рассылки одним сообщением.\nHTML/Markdown не требуется — текст будет отправлен как есть.")


@router.message(MailingState.waiting_message)
async def mailing_message(message: Message, state: FSMContext):
    if not await is_owner(message):
        await state.clear(); return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст сообщения.")
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        campaign = MarketingCampaign(name=data["name"], message=text, created_by=message.from_user.id, status=CampaignStatus.DRAFT.value)
        session.add(campaign)
        await session.commit()
        cid = campaign.id
        await write_audit(session, actor_telegram_id=message.from_user.id, action="marketing_campaign_created", entity_type="marketing_campaign", entity_id=str(cid), payload={"name": campaign.name})
    await state.clear()
    async with SessionLocal() as session:
        groups = (await session.execute(select(GuestGroup).order_by(GuestGroup.name))).scalars().all()
    await message.answer(f"📣 Кампания #{cid} создана.\n\nВыберите аудиторию:", reply_markup=audience_keyboard(groups))


async def build_snapshot(campaign_id: int, *, group_id: int | None, all_consent: bool, actor_id: int):
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if campaign is None or campaign.status != CampaignStatus.DRAFT.value:
            return None, "Кампания не найдена или уже не является черновиком."

        if group_id is not None:
            campaign_group = MarketingCampaignGroup(campaign_id=campaign.id, guest_group_id=group_id)
            session.add(campaign_group)
            query = (
                select(GuestTelegram, Guest)
                .join(Guest, Guest.id == GuestTelegram.guest_id)
                .join(GuestGroupMember, GuestGroupMember.guest_id == Guest.id)
                .where(GuestGroupMember.guest_group_id == group_id, GuestTelegram.marketing_consent.is_(True))
            )
        else:
            query = select(GuestTelegram, Guest).join(Guest, Guest.id == GuestTelegram.guest_id).where(GuestTelegram.marketing_consent.is_(True))

        rows = (await session.execute(query)).all()
        existing = set((await session.execute(select(MarketingRecipient.guest_id).where(MarketingRecipient.campaign_id == campaign.id))).scalars().all())
        added = 0
        for link, guest in rows:
            if guest.id in existing:
                continue
            session.add(MarketingRecipient(campaign_id=campaign.id, guest_id=guest.id, telegram_chat_id=link.telegram_chat_id))
            added += 1
        await session.commit()
        await write_audit(session, actor_telegram_id=actor_id, action="marketing_snapshot_created", entity_type="marketing_campaign", entity_id=str(campaign.id), payload={"group_id": group_id, "all_consent": all_consent, "recipients_added": added})
        total = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign.id))
        return campaign, total or 0


@router.callback_query(F.data.startswith("mail_group:"))
async def select_mail_group(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    group_id = int(callback.data.split(":")[1])
    campaign_id = await _latest_draft(callback.from_user.id)
    if campaign_id is None:
        await callback.answer("Черновик не найден", show_alert=True); return
    campaign, total = await build_snapshot(campaign_id, group_id=group_id, all_consent=False, actor_id=callback.from_user.id)
    if campaign is None:
        await callback.answer(str(total), show_alert=True); return
    await callback.message.answer(f"🎯 Snapshot готов для кампании #{campaign.id}.\nПолучателей с согласием: {total}\n\nНазвание: {campaign.name}\n\nТекст:\n{campaign.message}", reply_markup=campaign_keyboard(campaign.id))
    await callback.answer()


@router.callback_query(F.data == "mail_all")
async def select_mail_all(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    campaign_id = await _latest_draft(callback.from_user.id)
    if campaign_id is None:
        await callback.answer("Черновик не найден", show_alert=True); return
    campaign, total = await build_snapshot(campaign_id, group_id=None, all_consent=True, actor_id=callback.from_user.id)
    if campaign is None:
        await callback.answer(str(total), show_alert=True); return
    await callback.message.answer(f"🎯 Snapshot готов для кампании #{campaign.id}.\nПолучателей с согласием: {total}\n\nНазвание: {campaign.name}\n\nТекст:\n{campaign.message}", reply_markup=campaign_keyboard(campaign.id))
    await callback.answer()


async def _latest_draft(owner_id: int) -> int | None:
    async with SessionLocal() as session:
        q = await session.execute(select(MarketingCampaign.id).where(MarketingCampaign.created_by == owner_id, MarketingCampaign.status == CampaignStatus.DRAFT.value).order_by(MarketingCampaign.id.desc()).limit(1))
        return q.scalar_one_or_none()


@router.callback_query(F.data.startswith("mail_snapshot:"))
async def snapshot_info(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    cid = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, cid)
        total = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == cid))
        pending = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == cid, MarketingRecipient.status == RecipientStatus.PENDING.value))
        sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == cid, MarketingRecipient.status == RecipientStatus.SENT.value))
        failed = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == cid, MarketingRecipient.status == RecipientStatus.FAILED.value))
    if campaign is None:
        await callback.answer("Кампания не найдена", show_alert=True); return
    await callback.message.answer(f"📊 Snapshot #{cid}\nВсего: {total or 0}\nОжидают: {pending or 0}\nОтправлено: {sent or 0}\nОшибок: {failed or 0}")
    await callback.answer()


@router.callback_query(F.data.startswith("mail_send:"))
async def send_campaign(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    cid = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, cid)
        count = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == cid, MarketingRecipient.status == RecipientStatus.PENDING.value))
        if campaign is None or campaign.status not in {CampaignStatus.DRAFT.value, CampaignStatus.RUNNING.value}:
            await callback.answer("Кампания уже отправлена/отменена", show_alert=True); return
        if not count:
            await callback.answer("Нет получателей в snapshot", show_alert=True); return
        campaign.status = CampaignStatus.RUNNING.value
        campaign.confirmed_by = callback.from_user.id
        campaign.confirmed_at = datetime.now(timezone.utc)
        await session.commit()
        await write_audit(session, actor_telegram_id=callback.from_user.id, action="marketing_campaign_confirmed", entity_type="marketing_campaign", entity_id=str(cid), payload={"recipient_count": int(count)})
    await callback.answer("Отправка запущена")
    await _send_campaign(callback.message.bot, cid, callback.from_user.id)


async def _send_campaign(bot, campaign_id: int, actor_id: int):
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        recipients = (await session.execute(select(MarketingRecipient).where(MarketingRecipient.campaign_id == campaign_id, MarketingRecipient.status == RecipientStatus.PENDING.value).order_by(MarketingRecipient.id))).scalars().all()
    for recipient in recipients:
        try:
            await bot.send_message(chat_id=recipient.telegram_chat_id, text=campaign.message)
            async with SessionLocal() as session:
                row = await session.get(MarketingRecipient, recipient.id)
                if row:
                    row.status = RecipientStatus.SENT.value
                    row.sent_at = datetime.now(timezone.utc)
                    row.error = None
                    await session.commit()
            await asyncio.sleep(0.08)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after))
            try:
                await bot.send_message(chat_id=recipient.telegram_chat_id, text=campaign.message)
                status, error = RecipientStatus.SENT.value, None
            except Exception as retry_exc:
                status, error = RecipientStatus.FAILED.value, str(retry_exc)[:1000]
            async with SessionLocal() as session:
                row = await session.get(MarketingRecipient, recipient.id)
                if row:
                    row.status, row.error = status, error
                    row.sent_at = datetime.now(timezone.utc) if status == RecipientStatus.SENT.value else None
                    await session.commit()
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            async with SessionLocal() as session:
                row = await session.get(MarketingRecipient, recipient.id)
                if row:
                    row.status = RecipientStatus.FAILED.value
                    row.error = str(exc)[:1000]
                    await session.commit()
        except Exception as exc:
            async with SessionLocal() as session:
                row = await session.get(MarketingRecipient, recipient.id)
                if row:
                    row.status = RecipientStatus.FAILED.value
                    row.error = str(exc)[:1000]
                    await session.commit()

    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        pending = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == campaign_id, MarketingRecipient.status == RecipientStatus.PENDING.value))
        campaign.status = CampaignStatus.RUNNING.value if pending else CampaignStatus.COMPLETED.value
        await session.commit()
        await write_audit(session, actor_telegram_id=actor_id, action="marketing_campaign_finished", entity_type="marketing_campaign", entity_id=str(campaign_id), payload={"pending": int(pending or 0)})


@router.callback_query(F.data == "mail_cancel")
async def cancel_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Создание рассылки отменено.", reply_markup=mailing_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("mail_cancel_campaign:"))
async def cancel_campaign(callback: CallbackQuery):
    if not await is_owner(callback.message):
        await callback.answer("Нет доступа", show_alert=True); return
    cid = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        campaign = await session.get(MarketingCampaign, cid)
        if campaign is None or campaign.status != CampaignStatus.DRAFT.value:
            await callback.answer("Нельзя отменить эту кампанию", show_alert=True); return
        campaign.status = CampaignStatus.CANCELLED.value
        await session.commit()
        await write_audit(session, actor_telegram_id=callback.from_user.id, action="marketing_campaign_cancelled", entity_type="marketing_campaign", entity_id=str(cid))
    await callback.message.answer(f"❌ Кампания #{cid} отменена.", reply_markup=mailing_menu())
    await callback.answer()


@router.message(F.text == "🎯 Аудитории")
async def audiences(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count(GuestTelegram.id)).where(GuestTelegram.marketing_consent.is_(True)))
        groups = (await session.execute(select(GuestGroup).order_by(GuestGroup.name))).scalars().all()
        lines = [f"🎯 Аудитории\nВсе с согласием: {total or 0}"]
        for g in groups:
            count = await session.scalar(select(func.count(func.distinct(GuestTelegram.id))).join(Guest, Guest.id == GuestTelegram.guest_id).join(GuestGroupMember, GuestGroupMember.guest_id == Guest.id).where(GuestGroupMember.guest_group_id == g.id, GuestTelegram.marketing_consent.is_(True)))
            lines.append(f"• {g.name}: {count or 0}")
    await message.answer("\n".join(lines))


@router.message(F.text == "📜 История")
async def history(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    async with SessionLocal() as session:
        campaigns = (await session.execute(select(MarketingCampaign).order_by(MarketingCampaign.id.desc()).limit(20))).scalars().all()
        lines = ["📜 История рассылок:"]
        for c in campaigns:
            total = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == c.id))
            sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == c.id, MarketingRecipient.status == RecipientStatus.SENT.value))
            failed = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.campaign_id == c.id, MarketingRecipient.status == RecipientStatus.FAILED.value))
            lines.append(f"#{c.id} {c.name} — {c.status}; всего {total or 0}, отправлено {sent or 0}, ошибок {failed or 0}")
    await message.answer("\n".join(lines) if len(lines) > 1 else "История пуста.")


@router.message(F.text == "📊 Статистика рассылок")
async def mailing_stats(message: Message):
    if not await is_owner(message):
        await message.answer("⛔ Доступ только для владельца."); return
    async with SessionLocal() as session:
        campaigns = await session.scalar(select(func.count(MarketingCampaign.id)))
        sent = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.status == RecipientStatus.SENT.value))
        failed = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.status == RecipientStatus.FAILED.value))
        pending = await session.scalar(select(func.count(MarketingRecipient.id)).where(MarketingRecipient.status == RecipientStatus.PENDING.value))
    await message.answer(f"📊 Статистика рассылок\nКампаний: {campaigns or 0}\nУспешно: {sent or 0}\nОшибок: {failed or 0}\nОжидают: {pending or 0}")
