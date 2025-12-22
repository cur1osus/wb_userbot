import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio.session import AsyncSession
from telethon import TelegramClient

from bot.background_tasks import mailing, process_jobs, update_account_name
from bot.db.base import create_db_session_pool
from bot.db.func import RedisStorage
from bot.db.models import Account
from bot.scheduler import Scheduler
from bot.settings import se

# Создаём объект парсера аргументов
parser = argparse.ArgumentParser(description="Запуск Telegram-бота с аргументами")
parser.add_argument("path_session", type=str, help="Путь к сессии")
parser.add_argument("api_id", type=int, help="ID бота")
parser.add_argument("api_hash", type=str, help="Хэш бота")

# Парсим аргументы
args = parser.parse_args()
bot_path_session: str = args.path_session
bot_api_id: int = int(args.api_id)
bot_api_hash: str = args.api_hash


scheduler = Scheduler()


async def run_scheduler() -> None:
    while True:
        await scheduler.run_pending()
        await asyncio.sleep(1)


async def set_tasks(
    client: TelegramClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
):
    min_interval = max(60, se.mailing_interval_min_seconds)
    max_interval = max(min_interval, se.mailing_interval_max_seconds)

    mailing_job = scheduler.every(min_interval)
    mailing_job.seconds  # фиксируем единицу измерения

    async def _mailing_job():
        # Перед расчётом следующего запуска задаём новый случайный интервал.
        mailing_job.interval = random.randint(min_interval, max_interval)
        mailing_job.latest = None
        return await mailing(
            client,
            sessionmaker,
            storage,
        )

    mailing_job.do(_mailing_job)
    scheduler.every(15).seconds.do(
        process_jobs,
        client,
        sessionmaker,
        storage,
    )
    scheduler.every(3).hours.do(
        update_account_name,
        client,
        sessionmaker,
        storage,
    )


async def cache_account_identity(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: RedisStorage,
    path_session: str,
) -> int | None:
    async with sessionmaker() as session:
        result = await session.execute(
            select(Account.id).where(Account.path_session == path_session).limit(1)
        )
        account_id = result.scalar_one_or_none()

    if account_id is None:
        logger.error(
            "Не найден аккаунт с path_session=%s — записать в Redis нечего",
            path_session,
        )
        return None

    await storage.set("account_id", account_id)
    logger.info("Записали account_id=%s в Redis для текущей сессии", account_id)
    return account_id


async def init_telethon_client() -> TelegramClient | None:
    """Инициализация Telegram клиента"""
    try:
        client = TelegramClient(bot_path_session, bot_api_id, bot_api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("Сессия не авторизована")
            return None
        else:
            logger.info("Клиент Telegram инициализирован")
            return client
    except Exception as e:
        logger.exception(f"Ошибка при инициализации клиента: {e}")
        return None


async def main() -> None:
    logger.info("Запуск...")

    # Инициализация redis
    redis = await se.redis_dsn()

    # Инициализация клиентов БД
    engine, sessionmaker = await create_db_session_pool(se)

    client = await init_telethon_client()
    if not client:
        logger.error("Ошибка при инициализации клиента Telegram")
        exit()

    storage = RedisStorage(redis=redis, client_hash=bot_api_hash)

    account_id = await cache_account_identity(
        sessionmaker, storage, path_session=bot_path_session
    )
    if account_id is None:
        logger.error("Останавливаем бота: нет привязки аккаунта к сессии")
        return

    # Обновляем имя аккаунта сразу при старте, если оно пустое или изменилось.
    await update_account_name(client, sessionmaker, storage)

    await set_tasks(client, sessionmaker, storage)

    # Запуск планировщика и клиента
    try:
        logger.info("Запуск планировщика и клиента")
        await asyncio.gather(
            client.start(),  # pyright: ignore
            run_scheduler(),
        )
        await client.run_until_disconnected()  # pyright: ignore
    except Exception as e:
        logger.exception(f"Ошибка при запуске Клиента: {e}")
    finally:
        await client.disconnect()  # pyright: ignore
        logger.info("Клиент отключен")


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("schedule").setLevel(logging.WARNING)

    def _moscow_time(*args):
        # logging calls converter(timestamp, ...); ignore extra args.
        ts = args[0]
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Moscow")).timetuple()

    logging.Formatter.converter = _moscow_time

    # Формат логов
    f = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Обработчик для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(f)
    logger.addHandler(console_handler)

    # Подавляем шумные логи Telethon об обновлениях каналов
    logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)

    asyncio.run(main())
