"""
utils/morning_context.py
-------------------------
One snapshot of everything the morning needs, gathered once per day by plain
code: the calendar, reminders, tomorrow, the forecast and a few extras, the
open captures, Canberra headlines and an "on this day" item. The morning
podcast (jobs/podcast.py) and the morning message (jobs/morning.py) both read
the same snapshot, so the facts in the two can't disagree. Held in memory only:
a restart just means it is gathered again.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from agent.settings import settings
from utils import day_context, news

logger = logging.getLogger(__name__)


@dataclass
class MorningContext:
    day: date
    calendar: str = ""
    reminders: str = ""
    tomorrow: str = ""
    forecast: str = ""
    weather_extras: str = ""
    open_captures: str = ""
    headlines: list[dict] = field(default_factory=list)
    on_this_day: list[dict] = field(default_factory=list)


_cache: dict[date, MorningContext] = {}
_lock = threading.Lock()


def uv_label(index: float) -> str:
    return ("low" if index < 3 else "moderate" if index < 6 else "high" if index < 8
            else "very high" if index < 11 else "extreme")


def render_weather_extras(day: date) -> str:
    """Sunrise/sunset, UV and wind for `day` — the bits the forecast line
    leaves out. Empty when weather is off or Open-Meteo fails."""
    if not settings.weather_enabled:
        return ""
    from agent.tools.weather import call_open_meteo_forecast, call_open_meteo_search

    try:
        place = call_open_meteo_search(settings.default_location)["results"][0]
        data = call_open_meteo_forecast(
            place["latitude"],
            place["longitude"],
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "sunrise,sunset,uv_index_max,wind_speed_10m_max,apparent_temperature_max",
                "timezone": settings.timezone,
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
            },
        )["daily"]
        sunrise = datetime.fromisoformat(data["sunrise"][0]).strftime("%-I:%M %p")
        sunset = datetime.fromisoformat(data["sunset"][0]).strftime("%-I:%M %p")
        return (
            f"Sunrise {sunrise}, sunset {sunset}; UV up to {round(data['uv_index_max'][0])} ({uv_label(data['uv_index_max'][0])}); "
            f"wind up to {round(data['wind_speed_10m_max'][0])} km/h; "
            f"feels like up to {round(data['apparent_temperature_max'][0])} C."
        )
    except Exception as e:
        logger.warning("Weather extras failed: %s", e)
        return ""


def gather(today: date) -> MorningContext:
    tomorrow = today + timedelta(days=1)
    return MorningContext(
        day=today,
        calendar="\n".join(
            line
            for line in (
                day_context.render_calendar(today, today, generated=False),
                day_context.render_plan_window(today),
            )
            if line
        ),
        reminders=day_context.render_reminders(today, today),
        tomorrow=day_context.render_calendar(tomorrow, tomorrow),
        forecast=day_context.render_forecast(today, tomorrow),
        weather_extras=render_weather_extras(today),
        open_captures=day_context.render_open_captures(today),
        headlines=news.fetch_headlines(),
        on_this_day=news.fetch_on_this_day(today),
    )


def get_context(today: date, *, refresh: bool = False) -> MorningContext:
    """The day's snapshot, gathered on first use (or when `refresh`)."""
    with _lock:
        if refresh or today not in _cache:
            _cache.clear()
            _cache[today] = gather(today)
        return _cache[today]


def render_headlines(headlines: list[dict]) -> str:
    return "\n".join(f"- {h['title']} ({h['source']})\n  {h['link']}" for h in headlines)
