import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.date import DateTrigger
from langchain_core.tools import tool

from agent.scheduler import scheduler
from agent.settings import settings
from jobs.reminders import fire_reminder
from utils import reminders_store
from utils.datetime import parse_local_datetime

logger = logging.getLogger(__name__)


def _create_reminder(message: str, when: str) -> str:
    """Shared by set_reminder/set_timer: parse `when` (the assistant
    resolves relative language like "in 10 minutes" into an absolute
    date/time before calling, per the date/time grounding rule in the
    system prompt — see agent/graph.py), persist it, and schedule delivery."""
    try:
        due_local = parse_local_datetime(when)
    except (ValueError, AttributeError):
        return f"I couldn't understand the time '{when}'. Try an absolute date and time."

    reminder_id = str(uuid.uuid4())
    due_epoch = int(due_local.astimezone(timezone.utc).timestamp())

    reminders_store.create_reminder(reminder_id, message, due_epoch)
    scheduler.add_job(
        fire_reminder,
        trigger=DateTrigger(run_date=due_local),
        args=[reminder_id],
        id=f"reminder:{reminder_id}",
        replace_existing=True,
    )

    logger.info("Reminder set: '%s' at %s (id=%s)", message, due_local.isoformat(), reminder_id)
    return f"Got it — I'll remind you to '{message}' at {due_local.strftime('%A, %d %B %Y %I:%M %p')}."


@tool
def set_reminder(message: str, when: str) -> str:
    """Set a one-off reminder for the user.

    Args:
        message: What to remind the user about.
        when: An absolute local date/time to fire the reminder (resolve
              relative language like "in 10 minutes" or "tomorrow at 9am"
              into an absolute date/time yourself first, per the date/time
              grounding rule).
    """
    return _create_reminder(message, when)


@tool
def set_timer(when: str, message: Optional[str] = None) -> str:
    """Set a timer for the user — equivalent to a reminder with a default message.

    Args:
        when: An absolute local date/time the timer should go off (resolve
              relative language like "in 10 minutes" into an absolute
              date/time yourself first, per the date/time grounding rule).
        message: What to remind the user about. Defaults to a generic
                 "Timer's up!" message.
    """
    return _create_reminder(message or "Timer's up!", when)


@tool
def list_reminders() -> str:
    """List the user's currently pending reminders."""
    pending = reminders_store.list_pending()
    if not pending:
        return "You have no pending reminders."

    lines = []
    for r in pending:
        due_local = datetime.fromtimestamp(r["due_at"], tz=timezone.utc).astimezone(settings.zoneinfo())
        lines.append(f"- {r['message']} (due {due_local.strftime('%A, %d %B %Y %I:%M %p')})")
    return "\n".join(lines)


@tool
def cancel_reminder(message: str) -> str:
    """Cancel a pending reminder by matching text from its message.

    Args:
        message: Text to match against pending reminders' messages (a
                 substring is enough, e.g. "oven" matches "check the oven").
    """
    matches = reminders_store.find_pending_by_text(message)
    if not matches:
        return f"No pending reminder matching '{message}'."
    if len(matches) > 1:
        options = "; ".join(m["message"] for m in matches)
        return f"That matches more than one reminder — be more specific: {options}"

    r = matches[0]
    reminders_store.mark_status(r["id"], "cancelled")
    try:
        scheduler.remove_job(f"reminder:{r['id']}")
    except JobLookupError:
        pass
    return f"Cancelled reminder: '{r['message']}'."
