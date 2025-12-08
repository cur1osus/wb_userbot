import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.hints import EntityLike

logger = logging.getLogger(__name__)


@dataclass
class UserData:
    username: str
    item_name: str


greetings_morning = [
    "доброе утро",
    "утро доброе",
]

greetings_day = [
    "добрый день",
    "доброго дня",
]

greetings_evening = [
    "добрый вечер",
    "приятного вечера",
    "рада знакомству, добрый вечер",
]

greetings_night = [
    "доброй ночи",
]

greetings_anytime = [
    "здравствуйте",
    "приветствую",
    "доброго времени суток",
]

clarifying_texts = [
    "предложение по кешбэку на {item} ещё актуально?",
    "кешбэк на {item} сейчас действует?",
    "по {item} кешбэк ещё предлагается?",
    "работает ли кешбэк за {item}?",
    "на {item} кешбэк всё ещё в силе?",
    "я ещё могу рассчитывать на кешбэк за {item}?",
    "расскажите, действует ли кешбэк на {item} сейчас?",
    "я присматривалась к {item}, кешбэк доступен?",
    "получится ли оформить кешбэк за {item} сегодня?",
    "интересуюсь {item}: кешбэк сохраняется?",
    "я хотела уточнить, кешбэк на {item} ещё работает?",
    "кешбэк на {item} активен или уже закрыли?",
    "успеваю ли я на кешбэк по {item}?",
    "могу ли я оформить кешбэк на {item} прямо сейчас?",
    "уточните, пожалуйста, по {item} кешбэк в силе?",
]

follow_up_texts = [
    "если да, расскажите, пожалуйста, условия",
    "готова оформить сегодня, если всё ещё в силе",
    "если предложение актуально, напишите детали",
    "готова обсудить условия кешбэка",
    "буду благодарна за короткий ответ",
    "буду рада, если подскажете детали",
    "готова сразу оформить, если условия подходят",
    "мне важно понять условия, расскажите, пожалуйста",
    "если всё ок, сразу сделаю заказ",
    "расскажите коротко, как активировать кешбэк",
    "буду признательна за быстрый ответ",
    "напишите коротко, как активировать кешбэк",
    "если всё актуально, готова оформить сразу",
]

lead_in_texts = [
    "",
    "подскажите, ",
    "можно уточнить, ",
    "интересует, ",
    "скажите, пожалуйста, ",
    "а скажите, ",
    "хочу уточнить, ",
    "интересно узнать, ",
]

closing_texts = [
    "",
    "спасибо!",
    "заранее спасибо",
    "жду ваш ответ",
    "буду признательна",
    "буду рада ответу",
]


def _pick_greeting() -> str:
    """
    Выбираем приветствие по московскому времени, добавляя случайность.
    """
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    hour = now.hour

    if 5 <= hour < 12:
        pool = greetings_morning
    elif 12 <= hour < 18:
        pool = greetings_day
    elif 18 <= hour < 23:
        pool = greetings_evening
    else:
        pool = greetings_night

    # Иногда используем нейтральное приветствие, чтобы разнообразить тон.
    if random.random() < 0.25:
        pool = pool + greetings_anytime

    return random.choice(pool).capitalize()


async def send_message_safe(
    client: TelegramClient,
    entity: EntityLike,
    messages: list[str],
    *,
    delay: float = 1.0,
):
    success = False
    _more_than_one_message = len(messages) > 1
    for message in messages:
        try:
            await client.send_message(entity, message)
            success = True
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            return False
        if _more_than_one_message:
            await asyncio.sleep(delay)
    return success


async def randomize_text_message(item_name: str) -> str | list[str]:
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

    greeting = _pick_greeting()
    lead_in = random.choice(lead_in_texts)
    question = random.choice(clarifying_texts).format(item=item)

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
    follow_up = random.choice(follow_up_texts)
    follow_has_gratitude = any(
        kw in follow_up.lower()
        for kw in ("благодар", "признател", "рада", "спасибо")
    )

    closing_choice = random.choice(closing_texts) if closing_texts else ""
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

    use_follow_up = random.random() < 0.75
    if use_follow_up:
        follow_sentence = _with_punctuation(
            follow_up.capitalize(), probability=0.3
        )
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
