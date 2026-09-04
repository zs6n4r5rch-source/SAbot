import re
from urllib.request import Request, urlopen
from sqlalchemy import select
from fastapi import APIRouter, HTTPException, Request as FastRequest

from app.models.smm import SMMAccess
from app.models import TelegramUser, UserRole
from app.webapp.app import current_user

router = APIRouter()

SOURCES = [
    {"id": "2gis", "name": "2ГИС — отзывы", "url": "https://2gis.ru/volgograd/firm/70000001113863070/tab/reviews", "kind": "reviews", "manual": True},
    {"id": "vk", "name": "VK — Strike Arena", "url": "https://vk.ru/club239503445", "kind": "social", "manual": True},
    {"id": "telegram", "name": "Telegram — Strike Arena", "url": "https://t.me/strikevolgograd", "kind": "social", "manual": False},
    {"id": "yandex", "name": "Яндекс Карты — Strike Arena", "url": "https://yandex.ru/maps/org/strike_arena/11858963369?si=1ue016e7r8k51qhzph7v3mafrr", "kind": "reviews", "manual": True},
]


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 StrikeArenaAnalytics/1.0"})
    with urlopen(req, timeout=8) as response:
        return response.read().decode("utf-8", errors="ignore")[:500000]


def _number(patterns, text):
    for pattern in patterns:
        m = re.search(pattern, text, re.I | re.S)
        if m:
            raw = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
            try:
                return float(raw)
            except ValueError:
                pass
    return None


async def _access(request: FastRequest):
    user, _ = await current_user(request)
    if user.role == UserRole.OWNER.value:
        return user
    async with __import__("app.db.session", fromlist=["SessionLocal"]).SessionLocal() as session:
        access = await session.scalar(select(SMMAccess).where(SMMAccess.telegram_user_id == user.telegram_id, SMMAccess.active.is_(True)))
        if not access or "social" not in {x.strip() for x in access.analytics_access.split(",") if x.strip()}:
            raise HTTPException(403, "SMM social analytics access required")
    return user


@router.get("/api/social/sources")
async def social_sources(request: FastRequest):
    await _access(request)
    result = []
    for src in SOURCES:
        item = {**src, "status": "manual", "live": {}}
        if not src["manual"]:
            try:
                html = await __import__("asyncio").to_thread(_fetch, src["url"])
                subscribers = _number([r"(\d[\d\s]*)\s+subscribers", r"(\d[\d\s]*)\s+подписчик"], html)
                item["status"] = "live" if subscribers is not None else "live_unparsed"
                if subscribers is not None:
                    item["live"]["subscribers"] = int(subscribers)
            except Exception as exc:
                item["status"] = "unavailable"
                item["error"] = str(exc)[:160]
        result.append(item)
    return {"items": result}


@router.post("/api/social/recommendations")
async def social_recommendations(request: FastRequest):
    await _access(request)
    payload = await request.json()
    metrics = payload.get("metrics") or {}
    recs = []

    for source_id, m in metrics.items():
        name = next((x["name"] for x in SOURCES if x["id"] == source_id), source_id)
        rating = m.get("rating")
        reviews = m.get("reviews")
        posts = m.get("posts")
        reach = m.get("reach")
        engagement = m.get("engagement")
        replies = m.get("replies")
        if rating is not None:
            try:
                rating = float(rating)
                if rating < 4.5:
                    recs.append({"source": name, "priority": "high", "title": "Репутация требует внимания", "text": f"Рейтинг {rating:.1f}. Разобрать негативные отзывы, найти повторяющиеся причины и закрыть их контентом/сервисными изменениями."})
                elif rating >= 4.8:
                    recs.append({"source": name, "priority": "medium", "title": "Использовать сильную репутацию", "text": "Высокий рейтинг стоит превращать в контент: кейсы гостей, цитаты отзывов и понятный призыв к записи."})
            except (TypeError, ValueError):
                pass
        if reviews is not None and replies is not None:
            try:
                if float(reviews) > 0 and float(replies) / float(reviews) < 0.8:
                    recs.append({"source": name, "priority": "medium", "title": "Повысить долю ответов", "text": "Не оставлять отзывы без ответа. В первую очередь закрывать новые и негативные обращения."})
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if posts is not None and reach is not None:
            try:
                p, r = float(posts), float(reach)
                if p > 0 and r / p < 100:
                    recs.append({"source": name, "priority": "medium", "title": "Улучшить контент-дистрибуцию", "text": "Охват на публикацию низкий относительно объёма контента. Тестировать первые 2 секунды/первые строки, обложки, локальные офферы и время публикации."})
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if engagement is not None:
            try:
                e = float(engagement)
                if e < 3:
                    recs.append({"source": name, "priority": "high", "title": "Поднять вовлечённость", "text": "Добавить форматы с действием: опросы, сравнения, челленджи, результаты игр, реакции гостей и короткие CTA вместо только информационных постов."})
                elif e >= 8:
                    recs.append({"source": name, "priority": "low", "title": "Масштабировать работающий формат", "text": "Вовлечённость высокая. Найти 3 лучших публикации и повторить их механику в новых темах."})
            except (TypeError, ValueError):
                pass

    if not recs:
        recs = [
            {"source": "Все площадки", "priority": "medium", "title": "Заполнить базовые метрики", "text": "Для точных рекомендаций внеси за период подписчиков/охват/публикации, а для 2ГИС и Яндекс — рейтинг, число отзывов и долю отвеченных отзывов."},
            {"source": "Все площадки", "priority": "medium", "title": "Связать соцсети с продажами", "text": "Использовать отдельные UTM-ссылки и промокоды для VK и Telegram, чтобы связывать контент с регистрациями, визитами и выручкой."},
        ]
    return {"recommendations": recs}
