"""
Модуль парсинга расписания МИТСО.
Прямой POST-запрос с CSRF-токеном — без Playwright.
Сайт возвращает HTML, парсим через BeautifulSoup.
"""

import asyncio
import logging
import certifi
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://apps.mitso.by/frontend/web/schedule/group-schedule"

# --- Значения формы (латиницей, как их видит сайт) ---
FORM_DATA = {
    "ScheduleSearch[fak]": "YUridicheskij",
    "ScheduleSearch[form]": "Dnevnaya",
    "ScheduleSearch[kurse]": "3 kurs",
    "ScheduleSearch[group_class]": "2440 MP",  # латиница!
}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


async def _get_csrf_token(client: httpx.AsyncClient) -> str:
    """
    Открывает страницу расписания и достаёт CSRF-токен.
    Yii2 кладёт его в <meta name="csrf-token"> или hidden input.
    """
    resp = await client.get(BASE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    meta = soup.find("meta", {"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]

    hidden = soup.find("input", {"name": "_csrf-frontend"})
    if hidden and hidden.get("value"):
        return hidden["value"]

    raise RuntimeError("Не удалось найти CSRF-токен на странице")


async def fetch_schedule(target_date: Optional[datetime] = None) -> list[dict]:
    """
    Загружает расписание на указанную дату (по умолчанию — на завтра).
    Возвращает список пар вида:
      {"pair": 1, "subject": "...", "time": "08.15-9.35",
       "start_time": "08:15", "audience": "307"}
    """
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)

    # Если сегодня воскресенье — завтра начинается новая неделя → week=1
    today = datetime.now()
    week_value = "1" if today.weekday() == 6 else "0"

    async with httpx.AsyncClient(
    timeout=20,
    follow_redirects=True,
    verify=certifi.where(),   # <-- явно указываем путь к CA-бандлу certifi
) as client:
        try:
            token = await _get_csrf_token(client)
        except Exception as e:
            logger.exception("Ошибка получения CSRF-токена: %s", e)
            return []

        payload = {
            "_csrf-frontend": token,
            **FORM_DATA,
            "ScheduleSearch[week]": week_value,
        }

        try:
            resp = await client.post(BASE_URL, data=payload)
            resp.raise_for_status()
        except Exception as e:
            logger.exception("Ошибка POST-запроса: %s", e)
            return []

        return _parse_html(resp.text, target_date)


def _parse_html(html: str, target_date: datetime) -> list[dict]:
    """Извлекает пары на нужный день из HTML-ответа."""
    soup = BeautifulSoup(html, "lxml")

    # Формируем строку, как на сайте: "21 сентября"
    target_str = f"{target_date.day} {MONTHS_RU[target_date.month]}"

    # Ищем любой заголовок, содержащий "21 сентября"
    for header in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = header.get_text(strip=True)
        if target_str in text:
            table = header.find_next("table")
            if not table:
                logger.warning("Таблица после '%s' не найдена", text)
                return []
            return _parse_table(table)

    logger.warning("День '%s' не найден в расписании", target_str)
    return []


def _parse_table(table) -> list[dict]:
    """Парсит HTML-таблицу: столбцы [Время, Дисциплина, Аудитория]."""
    pairs: list[dict] = []
    pair_num = 0

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue  # пропускаем заголовок <th>

        time_str = cells[0].get_text(strip=True)
        subject = cells[1].get_text(strip=True)
        audience = cells[2].get_text(strip=True) if len(cells) >= 3 else ""

        pair_num += 1  # нумерация пар идёт по строкам, включая пустые

        # Пустая пара — пропускаем, но нумерацию сохраняем
        if not subject or "нет занятий" in subject.lower():
            continue

        # Из "08.15-9.35" достаём "08:15"
        start_time = None
        m = re.match(r"(\d{1,2})[.:](\d{2})", time_str)
        if m:
            start_time = f"{int(m.group(1)):02d}:{m.group(2)}"

        pairs.append({
            "pair": pair_num,
            "subject": subject,
            "time": time_str,
            "start_time": start_time,
            "audience": audience,
        })

    return pairs


def fetch_schedule_sync(target_date: Optional[datetime] = None) -> list[dict]:
    return asyncio.run(fetch_schedule(target_date))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch_schedule_sync():
        print(item)