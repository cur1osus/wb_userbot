import asyncio
import logging
import random
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.hints import EntityLike

logger = logging.getLogger(__name__)


@dataclass
class UserData:
    username: str
    item_name: str


greetings_texts = [
    "здравствуйте",
    "добрый день",
    "доброго дня",
    "приветствую",
]

clarifying_texts = [
    "предложение по кешбэку на {item} ещё актуально?",
    "кешбэк на {item} сейчас действует?",
    "по {item} кешбэк ещё предлагается?",
    "работает ли кешбэк за {item}?",
    "на {item} кешбэк всё ещё в силе?",
]

follow_up_texts = [
    "если да, расскажите, пожалуйста, условия",
    "готова оформить сегодня, если всё ещё в силе",
    "если предложение актуально, напишите детали",
    "готова обсудить условия кешбэка",
    "буду благодарна за короткий ответ",
]

lead_in_texts = [
    "",
    "подскажите, ",
    "можно уточнить, ",
    "интересует, ",
    "скажите, пожалуйста, ",
]

closing_texts = [
    "",
    "спасибо!",
    "заранее спасибо",
    "жду ваш ответ",
]


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

    def _with_punctuation(text: str) -> str:
        if not text:
            return ""
        return text if text.endswith((".", "!", "?")) else f"{text}."

    greeting = random.choice(greetings_texts).capitalize()
    lead_in = random.choice(lead_in_texts)
    question = random.choice(clarifying_texts).format(item=item)
    follow_up = random.choice(follow_up_texts)
    closing = (
        _with_punctuation(random.choice(closing_texts).capitalize())
        if closing_texts
        else ""
    )

    base_question = f"{lead_in}{question}"
    base_question = base_question[0].upper() + base_question[1:]

    messages: list[str] = []

    # Случайно решаем, отправлять ли приветствие и разделять ли сообщения.
    split_greeting = random.random() < 0.5
    if split_greeting:
        messages.append(f"{greeting}!")
        messages.append(base_question)
    else:
        messages.append(f"{greeting}! {base_question}")

    use_follow_up = random.random() < 0.75
    if use_follow_up:
        follow_sentence = follow_up.capitalize()
        if closing:
            follow_sentence = f"{follow_sentence}. {closing}"
        else:
            follow_sentence = f"{follow_sentence}."

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
