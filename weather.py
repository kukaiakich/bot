"""
Модуль получения погоды через бесплатный API Open-Meteo.
Документация: https://open-meteo.com/en/docs
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import certifi
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import MINSK_LAT, MINSK_LON

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def get_weather_forecast(
    target_date: Optional[datetime] = None,
    departure_time: Optional[str] = None,
) -> dict:
    """
    Получает прогноз погоды на указанную дату.

    Args:
        target_date: Дата прогноза. По умолчанию — завтра.
        departure_time: Время выхода в формате "ЧЧ:ММ" для определения
                        температуры в момент выхода.

    Returns:
        {
            "temp_morning": float,   # температура в момент выхода
            "temp_day_max": float,   # дневной максимум
            "precipitation": float,  # мм осадков за день
            "weather_code": int,     # код погоды WMO
            "is_rain": bool,         # будет ли дождь
        }
    """
    if target_date is None:
        target_date = datetime.now() + timedelta(days=1)

    date_str = target_date.strftime("%Y-%m-%d")

    params = {
        "latitude": MINSK_LAT,
        "longitude": MINSK_LON,
        "hourly": "temperature_2m,precipitation,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "timezone": "Europe/Minsk",
        "start_date": date_str,
        "end_date": date_str,
    }

    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.exception("Ошибка запроса погоды: %s", e)
        return _default_weather()

    # --- Извлекаем почасовые данные ---
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precips = hourly.get("precipitation", [])
    codes = hourly.get("weather_code", [])

    temp_morning = None
    if departure_time and times:
        # Ищем ближайший час к времени выхода
        dep_hour = int(departure_time.split(":")[0])
        for i, t in enumerate(times):
            if t.endswith(f"T{dep_hour:02d}:00"):
                temp_morning = temps[i] if i < len(temps) else None
                break
    if temp_morning is None and temps:
        temp_morning = temps[0]  # fallback — первый час

    # --- Дневные данные ---
    daily = data.get("daily", {})
    temp_day_max = (daily.get("temperature_2m_max") or [0])[0]
    precip_sum = (daily.get("precipitation_sum") or [0])[0]
    weather_code = (daily.get("weather_code") or [0])[0]

    # Определяем, будет ли дождь (коды WMO 51-67, 80-82, 95-99)
    is_rain = (
        precip_sum > 0.5
        or weather_code in range(51, 68)
        or weather_code in range(80, 83)
    )

    return {
        "temp_morning": round(temp_morning, 1) if temp_morning is not None else 0,
        "temp_day_max": round(temp_day_max, 1),
        "precipitation": round(precip_sum, 1),
        "weather_code": weather_code,
        "is_rain": is_rain,
    }


def _default_weather() -> dict:
    """Возвращает заглушку при ошибке запроса."""
    return {
        "temp_morning": 0,
        "temp_day_max": 0,
        "precipitation": 0,
        "weather_code": 0,
        "is_rain": False,
    }


def get_weather_forecast_sync(
    target_date: Optional[datetime] = None,
    departure_time: Optional[str] = None,
) -> dict:
    """Синхронная обёртка над async get_weather_forecast."""
    return asyncio.run(get_weather_forecast(target_date, departure_time))