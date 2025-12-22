import asyncio
import logging
import random
import re
from typing import Any

import msgspec
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, functions
from telethon.errors.rpcerrorlist import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    PeerFloodError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
)
from telethon.tl import types

from bot.db.func import RedisStorage
from bot.db.models import Account, AccountTexts, Job, Username
from bot.settings import se
from bot.utils.func import build_text_pools, randomize_text_message, send_message_safe

logger = logging.getLogger(__name__)
_msgpack_encoder = msgspec.msgpack.Encoder()
_phone_privacy_configured = False
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def _account_label(account: Account) -> str:
    return account.name or account.phone or "неизвестный аккаунт"


def _normalize_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@")


def _is_valid_username(username: str) -> bool:
    return bool(username) and bool(_USERNAME_PATTERN.fullmatch(username))


def _build_stop_payload(account: Account) -> bytes:
    message = (
        f"Аккаунт {_account_label(account)}: пользователи закончились, бот остановлен."
    )
    return _msgpack_encoder.encode(message)


async def _get_folder_pinned_user_ids(client: TelegramClient) -> list[int]:
    """
    Возвращает user_id закреплённых диалогов из папки по названию из .env.
    """
    folder_name = se.pinned_dialog_folder_name
    if not folder_name:
        logger.warning("PINNED_DIALOG_FOLDER_NAME не указан — пропускаем обработку job")
        return []

    try:
        await client.catch_up()
        result = await client(functions.messages.GetDialogFiltersRequest())
    except Exception as e:  # noqa: BLE001
        logger.warning("Не удалось получить список папок: %s", e)
        return []

    dialog_filters: Any = getattr(result, "filters", result)
    for dialog_filter in dialog_filters:
        if not isinstance(dialog_filter, types.DialogFilter):
            continue

        raw_title = getattr(dialog_filter, "title", "")
        if hasattr(raw_title, "text"):
            raw_title = raw_title.text
        title = str(raw_title or "").strip().lower()
        if title != folder_name.lower():
            continue

        pinned_peers = getattr(dialog_filter, "pinned_peers", []) or []
        return [
            peer.user_id
            for peer in pinned_peers
            if getattr(peer, "user_id", None) is not None
        ]

    logger.warning("Папка с названием '%s' не найдена", folder_name)
    return []


async def _ensure_phone_hidden(client: TelegramClient) -> None:
    """
    Ставит приватность номера на "никто", чтобы он не раскрывался при добавлении.
    """
    global _phone_privacy_configured
    if _phone_privacy_configured:
        return

    try:
        await client(
            functions.account.SetPrivacyRequest(
                key=types.InputPrivacyKeyPhoneNumber(),
                rules=[types.InputPrivacyValueDisallowAll()],
            )
        )
        _phone_privacy_configured = True
    except Exception as e:  # noqa: BLE001
        logger.warning("Не удалось выставить приватность номера: %s", e)


async def update_account_name(
    client: TelegramClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
) -> None:
    """
    Раз в 3 часа обновляет name аккаунта в БД по данным из Telegram.
    """
    account_id_raw = await storage.get("account_id")
    try:
        account_id = int(account_id_raw)
    except (TypeError, ValueError):
        logger.warning(
            "Не удалось определить account_id для обновления имени (raw=%s)",
            account_id_raw,
        )
        return

    me = await client.get_me()
    if not me:
        logger.warning("get_me вернул None — пропускаем обновление имени")
        return

    name_parts = [me.first_name or "", me.last_name or ""]
    new_name = " ".join(filter(None, name_parts)) or (me.username or "")
    if not new_name:
        logger.warning("Имя для обновления пустое — пропускаем")
        return

    async with sessionmaker() as session:
        result = await session.execute(
            select(Account).where(Account.id == account_id).limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            logger.error("Аккаунт id=%s не найден в БД, не обновляем имя", account_id)
            return

        if account.name == new_name:
            logger.debug("Имя аккаунта id=%s уже актуально: %s", account_id, new_name)
            return

        account.name = new_name
        await session.commit()
        logger.info("Обновили имя аккаунта id=%s на '%s'", account_id, new_name)


async def mailing(
    client: TelegramClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
    *,
    batch_size: int = 5,
    base_delay: tuple[float, float] = (6.0, 12.0),
    cooldown_every: int = 2,
    cooldown_range: tuple[float, float] = (45.0, 120.0),
) -> None:
    """
    Рассылка сообщений пользователям, которым ещё не отправляли.

    Бот берёт свой account_id из Redis, чтобы отправлять только свои username.
    """
    max_send_attempts = 3
    account_id_raw = await storage.get("account_id")
    try:
        account_id = int(account_id_raw)
    except (TypeError, ValueError):
        logger.warning(
            "Не удалось определить account_id для рассылки (raw=%s)", account_id_raw
        )
        return

    async with sessionmaker() as session:
        account = await session.get(Account, account_id)
        if not account:
            return
        if not account.is_started or not account.is_connected:
            return
        account_texts_id = await session.scalar(
            select(AccountTexts.id).where(AccountTexts.account_id == account_id).limit(1)
        )
        if not account_texts_id:
            logger.warning(
                "Тексты для account_id=%s не настроены — рассылка остановлена",
                account_id,
            )
            return
        text_pools = await build_text_pools(session, account_texts_id)
        result = await session.execute(
            select(Username.id, Username.username, Username.item_name)
            .where(
                Username.sended.is_(False),
                Username.account_id == account_id,
            )
            .order_by(Username.id)
            .limit(account.batch_size)
        )
        targets = [
            {"id": row.id, "username": row.username, "item_name": row.item_name}
            for row in result.all()
        ]

        if not targets:
            logger.info("Нет пользователей для рассылки")
            account.is_started = False
            session.add(
                Job(
                    account_id=account.id,
                    name="account_notification",
                    answer=_build_stop_payload(account),
                )
            )
            await session.commit()
            logger.info("Пользователи закончились — ставим бота на стоп")
            return

        logger.info("Начинаем рассылку: %s получателей", len(targets))

        sent = 0
        for idx, username_row in enumerate(targets, start=1):
            username_id = username_row["id"]
            username_value_raw = username_row["username"]
            item_name_value = username_row["item_name"]
            username_value = _normalize_username(username_value_raw)
            if not _is_valid_username(username_value):
                await session.execute(delete(Username).where(Username.id == username_id))
                await session.commit()
                logger.info(
                    "Удаляем некорректный username перед отправкой: @%s",
                    username_value or username_value_raw,
                )
                continue

            messages_raw = await randomize_text_message(item_name_value, text_pools)
            messages = (
                messages_raw if isinstance(messages_raw, list) else [messages_raw]
            )

            delay = random.uniform(*base_delay)
            await asyncio.sleep(delay)

            attempt = 0
            success = False
            skip_deletion = False
            stop_mailing = False

            while attempt < max_send_attempts and not success:
                attempt += 1
                try:
                    success = await send_message_safe(
                        client,
                        username_value,
                        messages,
                        delay=random.uniform(0.8, 1.6),
                    )
                except FloodWaitError as e:
                    wait_time = e.seconds + random.randint(3, 12)
                    logger.warning(
                        "FloodWait на @%s: спим %s сек", username_value, wait_time
                    )
                    await asyncio.sleep(wait_time)
                    skip_deletion = True
                    break
                except PeerFloodError:
                    logger.error(
                        "Telegram ограничил отправку (PeerFlood). Останавливаемся."
                    )
                    stop_mailing = True
                    break
                except (PeerIdInvalidError, UsernameInvalidError):
                    logger.info(
                        "Некорректный username/peer для @%s — удаляем запись",
                        username_value,
                    )
                    break
                except (
                    UserPrivacyRestrictedError,
                    UserIsBlockedError,
                    UserDeactivatedError,
                    UserDeactivatedBanError,
                    ChatWriteForbiddenError,
                ) as e:
                    logger.info("Не можем написать @%s: %s", username_value, e)
                    await session.execute(
                        update(Username)
                        .where(Username.id == username_id)
                        .values(sended=True)
                    )
                    await session.commit()
                    skip_deletion = True
                    break
                except Exception as e:  # noqa: BLE001
                    logger.exception(
                        "Ошибка при отправке @%s (попытка %s/%s): %s",
                        username_value,
                        attempt,
                        max_send_attempts,
                        e,
                    )
                    await session.rollback()

                if success:
                    break

                if (
                    attempt < max_send_attempts
                    and not skip_deletion
                    and not stop_mailing
                ):
                    retry_delay = random.uniform(2.0, 5.0)
                    logger.warning(
                        "Повторяем отправку @%s (попытка %s/%s) через %.1f сек",
                        username_value,
                        attempt + 1,
                        max_send_attempts,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

            if stop_mailing:
                break

            if success:
                await session.execute(
                    update(Username)
                    .where(Username.id == username_id)
                    .values(sended=True)
                )
                await session.commit()
                sent += 1
            elif not skip_deletion:
                await session.execute(delete(Username).where(Username.id == username_id))
                await session.commit()
                logger.info(
                    "Удалили запись для @%s после %s неудачных попыток отправки",
                    username_value,
                    max_send_attempts,
                )

            if skip_deletion and not success:
                continue

            if idx % cooldown_every == 0:
                cooldown = random.uniform(*cooldown_range)
                logger.info(
                    "Антифрод-пауза после %s сообщений: %.1f сек", idx, cooldown
                )
                await asyncio.sleep(cooldown)

        logger.info("Рассылка завершена. Отправлено сообщений: %s", sent)

        remaining = await session.scalar(
            select(Username.id)
            .where(
                Username.sended.is_(False),
                Username.account_id == account_id,
            )
            .limit(1)
        )
        if remaining is None:
            account.is_started = False
            session.add(
                Job(
                    account_id=account.id,
                    name="account_notification",
                    answer=_build_stop_payload(account),
                )
            )
            await session.commit()
            logger.info("Пользователи закончились — ставим бота на стоп")


async def process_jobs(
    client: TelegramClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
) -> None:
    """
    Обрабатывает задания с name='get_names_and_usernames'.

    Берёт закреплённые чаты из папки по названию, сопоставляет их с моделью
    Username, добавляет контакты с именем item_name и сохраняет список
    в job.answer (msgpack).
    """
    account_id_raw = await storage.get("account_id")
    try:
        account_id = int(account_id_raw)
    except (TypeError, ValueError):
        logger.warning(
            "Не удалось определить account_id для обработки jobs (raw=%s)",
            account_id_raw,
        )
        return

    async with sessionmaker() as session:
        jobs_result = await session.execute(
            select(Job).where(
                Job.account_id == account_id,
                Job.name == "get_names_and_usernames",
                Job.answer.is_(None),
            )
        )
        jobs = list(jobs_result.scalars().all())
        if not jobs:
            return

        usernames_result = await session.execute(
            select(Username).where(Username.account_id == account_id)
        )
        usernames_map = {
            (row.username or "").lstrip("@").lower(): row
            for row in usernames_result.scalars().all()
        }

        await _ensure_phone_hidden(client)

        pinned_user_ids = await _get_folder_pinned_user_ids(client)
        if not pinned_user_ids:
            logger.warning(
                "В указанной папке нет закрепленных чатов или она не найдена"
            )
            return

        processed_pairs: list[str] = []
        for user_id in set(pinned_user_ids):
            try:
                entity = await client.get_entity(types.PeerUser(user_id=user_id))
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Не удалось получить сущность пользователя %s: %s", user_id, e
                )
                continue

            if not isinstance(entity, types.User):
                continue

            username = (entity.username or "").lstrip("@").lower()
            if not username:
                continue

            username_row = usernames_map.get(username)
            if not username_row:
                continue

            try:
                input_user = await client.get_input_entity(entity)
                if isinstance(input_user, types.InputPeerUser):
                    input_user = types.InputUser(
                        user_id=input_user.user_id, access_hash=input_user.access_hash
                    )
                await client(
                    functions.contacts.AddContactRequest(
                        id=input_user,
                        first_name=username_row.item_name or entity.first_name or "",
                        last_name="",
                        phone="",
                        add_phone_privacy_exception=False,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Не удалось добавить контакт @%s: %s", username, e)
                continue

            processed_pairs.append(
                f"{username_row.item_name or entity.first_name or ''} - @{entity.username}"
            )

        packed_answer = _msgpack_encoder.encode(processed_pairs)
        for job in jobs:
            job.answer = packed_answer

        await session.commit()
