import logging
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

@tool
def set_reminder(message: str, when: str) -> str:
    """Set a reminder for the user.

    Args:
        message: What to remind the user about.
        when: When to trigger the reminder, in natural language (e.g. "in 10 minutes",
              "tomorrow at 9am").
    """
    # Real implementation ideas:
    #   - Parse `when` with dateparser library
    #   - Store in SQLite with a timestamp
    #   - Use asyncio.create_task() or APScheduler to fire the reminder
    #   - Deliver via a WebSocket push, TTS on the ESP32, or a macOS notification
    logger.info("[STUB] Reminder set: '%s' at '%s'", message, when)
    return f"Got it — I'll remind you to '{message}' {when}."

@tool
def set_timer(when: str, message: Optional[str] = None) -> str:
    """Set a timer for the user.

    Args:
        message: What to remind the user about.
        when: When to trigger the reminder, in natural language (e.g. "in 10 minutes",
              "tomorrow at 9am").
    """
    # Real implementation ideas:
    #   - Parse `when` with dateparser library
    #   - Store in SQLite with a timestamp
    #   - Use asyncio.create_task() or APScheduler to fire the reminder
    #   - Deliver via a WebSocket push, TTS on the ESP32, or a macOS notification
    if message:
        logger.info("[STUB] Timer set: '%s' at '%s'", message, when)
        return f"Timer set for '{when}'."
    else:
        logger.info("[STUB] Timer set at '%s'", when)
        return f"Timer set for '{when}'."