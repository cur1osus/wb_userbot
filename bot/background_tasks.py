import asyncio
import logging
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerFloodError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
    UserPrivacyRestrictedError,
)

from bot.db.func import RedisStorage
from bot.db.models import Account, Username
from bot.utils.func import randomize_text_message, send_message_safe

logger = logging.getLogger(__name__)


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
        result = await session.execute(
            select(Username)
            .where(
                Username.sended.is_(False),
                Username.account_id == account_id,
            )
            .order_by(Username.id)
            .limit(batch_size)
        )
        targets = list(result.scalars().all())

        if not targets:
            logger.info("Нет пользователей для рассылки")
            return

        logger.info("Начинаем рассылку: %s получателей", len(targets))

        sent = 0
        for idx, username_row in enumerate(targets, start=1):
            messages_raw = await randomize_text_message(username_row.item_name)
            messages = (
                messages_raw if isinstance(messages_raw, list) else [messages_raw]
            )

            delay = random.uniform(*base_delay)
            await asyncio.sleep(delay)

            try:
                success = await send_message_safe(
                    client,
                    username_row.username,
                    messages,
                    delay=random.uniform(0.8, 1.6),
                )
            except FloodWaitError as e:
                wait_time = e.seconds + random.randint(3, 12)
                logger.warning(
                    "FloodWait на @%s: спим %s сек", username_row.username, wait_time
                )
                await asyncio.sleep(wait_time)
                continue
            except PeerFloodError:
                logger.error(
                    "Telegram ограничил отправку (PeerFlood). Останавливаемся."
                )
                break
            except (
                UserPrivacyRestrictedError,
                UserIsBlockedError,
                UserDeactivatedError,
                UserDeactivatedBanError,
                ChatWriteForbiddenError,
            ) as e:
                logger.info("Не можем написать @%s: %s", username_row.username, e)
                username_row.sended = True
                await session.commit()
                continue
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "Ошибка при отправке @%s: %s", username_row.username, e
                )
                await session.rollback()
                continue

            if success:
                username_row.sended = True
                await session.commit()
                sent += 1

            if idx % cooldown_every == 0:
                cooldown = random.uniform(*cooldown_range)
                logger.info(
                    "Антифрод-пауза после %s сообщений: %.1f сек", idx, cooldown
                )
                await asyncio.sleep(cooldown)

        logger.info("Рассылка завершена. Отправлено сообщений: %s", sent)
