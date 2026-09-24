"""
Telegram-бот для отслеживания расписания МИТСО.
Отправляет утренний дайджест каждый день в 06:15 и отвечает на /schedule.
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from config import (
    MORNING_HOUR,
    MORNING_MINUTE,
    DEPARTURE_MINUTES_BEFORE,
)
from parser import fetch_schedule
from weather import get_weather_forecast

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ID чата для утреннего дайджеста ---
# Узнать можно через @userinfobot в Telegram, вставь свой ID сюда:
TARGET_CHAT_ID: int = 712330091  # <-- ВСТАВЬ СВОЙ CHAT_ID


# ============================================================
#  Формирование сообщения
# ============================================================

async def build_digest() -> str:
    """
    Собирает текст утреннего дайджеста на завтра.
    Формат: название предмета + время + аудитория.
    """
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%d.%m.%Y")

    # --- Получаем расписание ---
    schedule = await fetch_schedule(tomorrow)

    if not schedule:
        return f"завтра ({date_str}) пар нет 🎉\nотдыхай!"

    # --- Первая пара определяет время выхода ---
    first_pair = schedule[0]
    first_pair_num = first_pair["pair"]
    first_start = first_pair.get("start_time") or "08:30"

    dep_hour, dep_min = map(int, first_start.split(":"))
    dep_dt = datetime(2000, 1, 1, dep_hour, dep_min) - timedelta(
        minutes=DEPARTURE_MINUTES_BEFORE
    )
    departure_time = dep_dt.strftime("%H:%M")

    # --- Погода ---
    weather = await get_weather_forecast(tomorrow, departure_time)

    # --- Что взять ---
    items = _get_items_to_bring(schedule, weather)
    items_str = ", ".join(items) if items else "ничего особенного"

    # --- Формируем сообщение ---
    lines = [f"завтра к {first_pair_num}-й паре Вась"]
    lines.append(_format_pair(first_pair))

    if len(schedule) > 1:
        lines.append("остальные пары:")
        for p in schedule[1:]:
            lines.append(_format_pair(p))

    lines.append(f"время выхода: {departure_time}")
    lines.append(
        f"погода: при выходе +{weather['temp_morning']}°C, "
        f"днем до +{weather['temp_day_max']}°C"
    )
    lines.append(f"взять: {items_str}")

    return "\n".join(lines)


def _format_pair(p: dict) -> str:
    """
    Форматирует одну пару в многострочный блок:
      1 пара
      📚 Матанализ
      🕐 08:15–09:35
      📍 ауд. 307
    Если время или аудитория отсутствуют — соответствующие строки не выводятся.
    """
    lines = [f"{p['pair']} пара", f"📚 {p['subject']}"]

    if p.get("time"):
        lines.append(f"🕐 {_normalize_time_range(p['time'])}")

    if p.get("audience"):
        lines.append(f"📍 ауд. {p['audience']}")

    return "\n".join(lines)


def _normalize_time_range(raw: str) -> str:
    """
    Преобразует строку времени из формата сайта ('08.15-9.35')
    в читаемый вид ('08:15–09:35').
    Использует en-dash (–) для красоты.
    """
    # Находим все пары "часы.минуты" или "часы:минуты"
    matches = re.findall(r"(\d{1,2})[.:](\d{2})", raw)
    if len(matches) >= 2:
        start = f"{int(matches[0][0]):02d}:{matches[0][1]}"
        end = f"{int(matches[1][0]):02d}:{matches[1][1]}"
        return f"{start}–{end}"
    return raw  # если формат не распознан — возвращаем как есть


def _get_items_to_bring(schedule: list[dict], weather: dict) -> list[str]:
    """
    Простая логика определения вещей для взятия.
    Легко расширяется.
    """
    items: list[str] = []

    # Проверяем наличие физкультуры
    has_pe = any(
        "физ" in item["subject"].lower() or "физическ" in item["subject"].lower()
        for item in schedule
    )
    if has_pe:
        items.append("спортивную форму")

    # Если ожидается дождь — зонт
    if weather.get("is_rain"):
        items.append("Капюшончик")

    # Если холодно (ниже +5) — тёплая куртка
    if weather.get("temp_morning", 0) < 5:
        items.append("Аляска куртку")

    # Если жарко (выше +25) — вода
    if weather.get("temp_day_max", 0) > 25:
        items.append("бутылку газявы вась сушняк")

    # Базовая вещь — всегда
    items.append("Пропуск")

    return items


# ============================================================
#  Обработчики команд
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие."""
    await message.answer(
        "Привет! Я бот для отслеживания расписания МИТСО.\n\n"
        "Команды:\n"
        "/schedule — расписание на завтра\n\n"
        "Утренний дайджест приходит каждый день в 06:15."
    )


@dp.message(Command("schedule"))
async def cmd_schedule(message: Message):
    """Ручной запрос расписания."""
    await message.answer("Загружаю расписание... ⏳")
    try:
        digest = await build_digest()
        await message.answer(digest)
    except Exception as e:
        logger.exception("Ошибка при формировании расписания: %s", e)
        await message.answer("Не удалось получить расписание. Попробуй позже.")


# ============================================================
#  Планировщик: утренний дайджест
# ============================================================

async def send_morning_digest():
    """Отправляет утренний дайджест в целевой чат."""
    if not TARGET_CHAT_ID:
        logger.warning("TARGET_CHAT_ID не задан — дайджест не отправлен")
        return

    try:
        digest = await build_digest()
        await bot.send_message(TARGET_CHAT_ID, digest)
        logger.info("Утренний дайджест отправлен в чат %d", TARGET_CHAT_ID)
    except Exception as e:
        logger.exception("Ошибка отправки утреннего дайджеста: %s", e)


# ============================================================
#  Точка входа
# ============================================================

async def main():
    """Запуск бота и планировщика."""
    # Настраиваем APScheduler
    scheduler = AsyncIOScheduler(timezone="Europe/Minsk")
    scheduler.add_job(
        send_morning_digest,
        CronTrigger(hour=MORNING_HOUR, minute=MORNING_MINUTE),
        id="morning_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Планировщик запущен. Дайджест будет приходить в %02d:%02d ежедневно.",
        MORNING_HOUR,
        MORNING_MINUTE,
    )

    # Запускаем polling
    logger.info("Бот запущен. Ожидаю сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())