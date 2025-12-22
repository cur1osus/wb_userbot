import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.hints import EntityLike
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    AccountTexts,
    ClarifyingText,
    ClosingText,
    FollowUpText,
    GreetingAnytime,
    GreetingDay,
    GreetingEvening,
    GreetingMorning,
    GreetingNight,
    LeadInText,
)

logger = logging.getLogger(__name__)


@dataclass
class UserData:
    username: str
    item_name: str


@dataclass
class TextPools:
    greetings_morning: list[str]
    greetings_day: list[str]
    greetings_evening: list[str]
    greetings_night: list[str]
    greetings_anytime: list[str]
    clarifying_texts: list[str]
    follow_up_texts: list[str]
    lead_in_texts: list[str]
    closing_texts: list[str]


def _normalize_texts(items: list[object]) -> list[str]:
    texts: list[str] = []
    for item in items:
        text = getattr(item, "text", "")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if text:
            texts.append(text)
    return texts


async def _fetch_texts(
    session: AsyncSession, model: type[AccountTexts], account_texts_id: int
) -> list[str]:
    result = await session.execute(
        select(model.text).where(model.account_texts_id == account_texts_id)
    )
    texts: list[str] = []
    for (text,) in result.all():
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                texts.append(stripped)
    return texts


async def build_text_pools(
    session: AsyncSession, account_texts_id: int
) -> TextPools:
    return TextPools(
        greetings_morning=await _fetch_texts(
            session, GreetingMorning, account_texts_id
        ),
        greetings_day=await _fetch_texts(session, GreetingDay, account_texts_id),
        greetings_evening=await _fetch_texts(
            session, GreetingEvening, account_texts_id
        ),
        greetings_night=await _fetch_texts(session, GreetingNight, account_texts_id),
        greetings_anytime=await _fetch_texts(
            session, GreetingAnytime, account_texts_id
        ),
        clarifying_texts=await _fetch_texts(
            session, ClarifyingText, account_texts_id
        ),
        follow_up_texts=await _fetch_texts(session, FollowUpText, account_texts_id),
        lead_in_texts=await _fetch_texts(session, LeadInText, account_texts_id),
        closing_texts=await _fetch_texts(session, ClosingText, account_texts_id),
    )


def _pick_greeting(text_pools: TextPools) -> str:
    """
    Выбираем приветствие по московскому времени, добавляя случайность.
    """
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    hour = now.hour

    if 5 <= hour < 12:
        base_pool = text_pools.greetings_morning
    elif 12 <= hour < 18:
        base_pool = text_pools.greetings_day
    elif 18 <= hour < 23:
        base_pool = text_pools.greetings_evening
    else:
        base_pool = text_pools.greetings_night

    # Иногда используем нейтральное приветствие, чтобы разнообразить тон.
    if random.random() < 0.25 and text_pools.greetings_anytime:
        pool = base_pool + text_pools.greetings_anytime
    else:
        pool = base_pool or text_pools.greetings_anytime

    if not pool:
        pool = (
            text_pools.greetings_anytime
            or text_pools.greetings_morning
            or text_pools.greetings_day
            or text_pools.greetings_evening
            or text_pools.greetings_night
        )
    if not pool:
        raise ValueError("В AccountTexts нет доступных приветствий.")

    return random.choice(pool).capitalize()


async def send_message_safe(
    client: TelegramClient,
    entity: EntityLike,
    messages: list[str],
    *,
    delay: float = 1.0,
):
    _more_than_one_message = len(messages) > 1
    for message in messages:
        try:
            await client.send_message(entity, message)
        except Exception as e:
            logger.error("Ошибка при отправке сообщения: %s", e)
            raise
        if _more_than_one_message:
            await asyncio.sleep(delay)
    return True


async def randomize_text_message(
    item_name: str,
    text_pools: TextPools,
) -> str | list[str]:
    item = item_name.strip() or "товар"

    def _with_punctuation(
        text: str, *, mark: str = ".", probability: float = 0.3
    ) -> str:
        if not text:
            return ""
        if text.endswith((".", "!", "?")):
            return text
        return f"{text}{mark}" if random.random() < probability else text

    def _format_greeting(greeting_text: str) -> tuple[str, bool]:
        # Иногда без восклицательного знака, чтобы звучало естественнее.
        punct = random.choices(["", "!", "."], weights=[0.35, 0.45, 0.2])[0]
        text = f"{greeting_text}{punct}".strip()
        has_punct = punct in ("!", ".", "?")
        return text, has_punct

    greeting = _pick_greeting(text_pools)
    lead_in = (
        random.choice(text_pools.lead_in_texts) if text_pools.lead_in_texts else ""
    )
    if not text_pools.clarifying_texts:
        raise ValueError("В AccountTexts нет уточняющих текстов.")
    question = random.choice(text_pools.clarifying_texts).format(item=item)

    # Если вопрос уже начинается с "расскажите/подскажите/скажите",
    # убираем вводную часть, чтобы избежать тавтологии.
    question_start = question.lstrip().lower()
    ask_prefixes = (
        "расскажите",
        "подскажите",
        "скажите",
        "интересуюсь",
        "интересует",
        "можно",
        "уточните",
        "хочу уточнить",
        "я хочу",
        "я хотела",
    )
    if question_start.startswith(ask_prefixes):
        lead_in = ""
    follow_up = (
        random.choice(text_pools.follow_up_texts) if text_pools.follow_up_texts else ""
    )
    follow_has_gratitude = any(
        kw in follow_up.lower() for kw in ("благодар", "признател", "рада", "спасибо")
    )

    closing_choice = (
        random.choice(text_pools.closing_texts) if text_pools.closing_texts else ""
    )
    closing = (
        _with_punctuation(closing_choice.capitalize(), probability=0.3)
        if closing_choice
        else ""
    )

    # Если follow_up уже содержит благодарность, убираем похожее закрытие,
    # чтобы не повторяться.
    if follow_has_gratitude and closing_choice:
        closing_has_gratitude = any(
            kw in closing_choice.lower()
            for kw in ("благодар", "признател", "спасибо", "рада")
        )
        if closing_has_gratitude:
            closing = ""

    base_question = f"{lead_in}{question}"
    base_question = base_question[0].upper() + base_question[1:]
    base_question_inline = base_question

    messages: list[str] = []

    # Случайно решаем, отправлять ли приветствие и разделять ли сообщения.
    split_greeting = random.random() < 0.5
    greeting_formatted, greeting_has_punct = _format_greeting(greeting)
    if not greeting_has_punct and base_question:
        base_question_inline = base_question[0].lower() + base_question[1:]

    if split_greeting:
        messages.append(greeting_formatted)
        messages.append(base_question)
    else:
        messages.append(f"{greeting_formatted} {base_question_inline}".strip())

    use_follow_up = bool(follow_up) and random.random() < 0.75
    if use_follow_up:
        follow_sentence = _with_punctuation(follow_up.capitalize(), probability=0.3)
        if closing:
            follow_sentence = f"{follow_sentence} {closing}".strip()

        split_follow = random.random() < 0.5
        if split_follow:
            messages.append(follow_sentence)
        else:
            messages[-1] = f"{messages[-1]} {follow_sentence}"
    elif closing and random.random() < 0.4:
        # Иногда добавляем только вежливое завершение без уточнений.
        messages[-1] = f"{messages[-1]} {closing}"

    return messages if len(messages) > 1 else messages[0]


async def parse_users_from_text(text: str) -> tuple[list[UserData], list[str]]:
    lines = text.splitlines()
    users = []
    line_not_handled = []
    for line in lines:
        if not line:
            continue
        r = line.split("-")
        if not r or len(r) < 2:
            line_not_handled.append(line)
            continue
        username = r[1].strip()
        item_name = r[0].strip()
        users.append(UserData(username, item_name))
    return users, line_not_handled
