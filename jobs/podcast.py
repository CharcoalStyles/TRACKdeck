"""
jobs/podcast.py
----------------
The morning podcast: a short two-host chat built from the same snapshot as the
morning message (utils/morning_context.py), written by the writer model,
spoken with Piper and saved as Podcasts/YYYY-MM-DD.mp3 (plus the script as
.md) in the vault. Runs before the morning message so the message can link to
it; the two never wait on each other.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from agent.settings import settings
from jobs.common import write
from utils import morning_context, tts, vault
from utils.notify import notify_error

logger = logging.getLogger(__name__)

PODCAST_DIRNAME = "Podcasts"
PODCAST_LEAD_MINUTES = 25  # starts this long before the morning message
KEEP_EPISODES = 30

# HOST leads, CO is the foil. Pairs rotate by day so the show changes voices
# now and then, but a re-run on the same day sounds the same.
VOICE_PAIRS = [
    ("en_GB-alan-medium", "en_GB-jenny_dioco-medium"),
    ("en_US-ryan-medium", "en_US-amy-medium"),
    ("en_GB-jenny_dioco-medium", "en_US-ryan-medium"),
    ("en_US-amy-medium", "en_GB-alan-medium"),
]

PODCAST_PROMPT = """You write the script for a short morning podcast with two hosts, in the \
brisk, friendly style of an Australian morning news briefing. The one listener is the person \
whose day this is. Today is {today}. Aim for about 650 to 800 words, roughly five minutes \
spoken.

Hosts: HOST leads and is warm; CO is dry and playful. Banter and jokes are welcome. Opinions \
about news, politics or people are not. Every line starts with "HOST:" or "CO:" and nothing \
else: no stage directions, no markdown, no links, no sound effects.

Write for the ear: short sentences, contractions, say times the way people do ("half past \
one", "a quarter to nine"), say "degrees" not "C". Facts come ONLY from the material below: \
never invent names, times, numbers, places, outlets or outcomes. A calendar entry is what was \
planned, not something the user did. Talk only about the topics listed, never mention that \
something is missing, empty, or all clear. Use news outlet names exactly as written. For each \
headline say only what its headline and summary say; with no summary, give the headline and \
add nothing. Never list a day plan's individual sprints; at most mention when the plan runs.

Cover, in this order: {topics}.

{material}"""

_SECTIONS = [
    # (ctx attribute, heading, topic sentence)
    ("forecast", "Forecast (today and tomorrow)", "the weather"),
    ("weather_extras", "More on today's weather", None),
    ("calendar", "Today's calendar", "what is on today"),
    ("reminders", "Today's reminders", None),
    ("tomorrow", "Tomorrow's calendar (a heads-up only)", "a heads-up on tomorrow"),
    ("open_captures", "Captures still open (unticked, carried over until done)",
     "the captures still open, lightly and without nagging"),
    ("headlines", "Canberra headlines", "two or three of the lightest Canberra headlines"),
    ("on_this_day", "On this day", "one \"on this day\" item, chosen and riffed on for a moment"),
]

_SPEAKER = re.compile(r"^\s*\**\s*(HOST|CO)\s*\**\s*:\s*\**\s*(.*\S)\s*$", re.IGNORECASE)


@dataclass
class Episode:
    day: date
    mp3: Path
    script: Path
    seconds: float


# Whether a run is in flight / the last failure, for the dashboard.
STATE = {"running": False, "error": None}


def podcast_dir() -> Path:
    return vault.vault_root() / PODCAST_DIRNAME


def mp3_path(day: date) -> Path:
    return podcast_dir() / f"{day.isoformat()}.mp3"


def script_path(day: date) -> Path:
    return podcast_dir() / f"{day.isoformat()}.md"


def episode_exists(day: date) -> bool:
    return mp3_path(day).exists()


def podcast_link() -> str:
    base = settings.public_base_url.strip().rstrip("/")
    return f"{base}/podcast" if base else ""


def pick_voices(day: date) -> dict[str, str]:
    host, co = VOICE_PAIRS[day.toordinal() % len(VOICE_PAIRS)]
    return {"HOST": host, "CO": co}


def build_prompt(ctx: morning_context.MorningContext) -> str:
    """Only the sections that have something in them go into the prompt, so
    the writer is never handed an empty one to comment on."""
    values = {
        "headlines": "\n".join(
            f"- [{h['source']}] {h['title']}: {h['summary'] or '(no summary)'}" for h in ctx.headlines
        ),
        "on_this_day": "\n".join(f"- {e['year']}: {e['text']}" for e in ctx.on_this_day),
    }
    blocks, topics = [], ["a greeting with the day and date"]
    for attr, heading, topic in _SECTIONS:
        text = (values.get(attr) if attr in values else getattr(ctx, attr)) or ""
        if not text.strip():
            continue
        blocks.append(f"{heading}:\n{text.strip()}")
        if topic and topic not in topics:
            topics.append(topic)
    topics.append("a short, warm sign-off")
    return PODCAST_PROMPT.format(
        today=ctx.day.strftime("%A %d %B %Y"),
        topics="; ".join(topics),
        material="\n\n".join(blocks),
    )


def parse_script(text: str) -> list[tuple[str, str]]:
    """(speaker, line) turns from the writer's HOST:/CO: lines. A line with no
    tag continues the previous turn; a script with no tags at all is one HOST turn."""
    turns: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        match = _SPEAKER.match(raw)
        if match:
            turns.append((match.group(1).upper(), match.group(2)))
        elif turns:
            turns[-1] = (turns[-1][0], f"{turns[-1][1]} {raw.strip()}")
        else:
            turns.append(("HOST", raw.strip()))
    return turns


def spoken(text: str) -> str:
    """Tidy one turn for Piper: no markdown or links, 24-hour times and unit
    symbols said the way a person would."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`~>]+", "", text)

    def clock(m: re.Match) -> str:
        hour, minute = int(m.group(1)), m.group(2)
        suffix = "AM" if hour < 12 else "PM"
        hour = hour % 12 or 12
        return f"{hour}:{minute} {suffix}" if minute != "00" else f"{hour} {suffix}"

    text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", clock, text)
    text = re.sub(r"(\d)\s?°\s?C\b", r"\1 degrees", text)
    text = re.sub(r"(\d)\s?C\b", r"\1 degrees", text)
    text = re.sub(r"(\d)\s?%", r"\1 percent", text)
    text = re.sub(r"\bkm/h\b", "kilometres an hour", text)
    return re.sub(r"\s+", " ", text).strip()


def samples_path() -> Path:
    return podcast_dir() / "voice-samples.mp3"


def generate_voice_samples() -> Path:
    """One MP3 of each voice pair saying a few lines, so the rotation can be
    judged by ear. Blocking."""
    from itertools import chain

    out = podcast_dir() / "voice-samples.mp3"
    voices: dict[str, str] = {}
    turns: list[tuple[str, str]] = []
    for n, (host, co) in enumerate(VOICE_PAIRS, start=1):
        voices[f"H{n}"], voices[f"C{n}"] = host, co
        turns += [
            (f"H{n}", f"Pair {n}. Good morning, I'm the host, and this is how I sound."),
            (f"C{n}", "And I'm the co-host. It's going to rain, apparently, so that's a shame."),
            (f"H{n}", "Sunrise is at six oh two, and you have a dentist appointment at a quarter to nine."),
        ]
    tts.render_mp3(turns, voices, out, "Voice samples")
    return out


def prune_old_episodes(keep: int = KEEP_EPISODES) -> None:
    mp3s = sorted(podcast_dir().glob("????-??-??.mp3"))
    for old in mp3s[:-keep]:
        old.unlink(missing_ok=True)
        old.with_suffix(".md").unlink(missing_ok=True)


def generate_episode(day: date, *, refresh: bool = False) -> Episode:
    """Blocking (feeds, LLM, TTS) — run via asyncio.to_thread."""
    ctx = morning_context.get_context(day, refresh=refresh)
    script = write(build_prompt(ctx), temperature=0.8)
    turns = [(s, spoken(t)) for s, t in parse_script(script)]
    turns = [(s, t) for s, t in turns if t]
    if not turns:
        raise RuntimeError("podcast script had no spoken lines")
    title = f"Morning Brief — {day.strftime('%A %d %B %Y')}"
    seconds = tts.render_mp3(turns, pick_voices(day), mp3_path(day), title)
    vault.write_note_atomic(script_path(day), f"# {title}\n\n{script.strip()}\n")
    prune_old_episodes()
    return Episode(day=day, mp3=mp3_path(day), script=script_path(day), seconds=seconds)


async def run_podcast(day: date | None = None, *, refresh: bool = False) -> Episode:
    """Generate today's episode, recording STATE for the dashboard. Raises on
    failure after notifying; callers that must not raise catch it."""
    day = day or datetime.now(settings.zoneinfo()).date()
    if STATE["running"]:
        raise RuntimeError("a podcast is already being made")
    STATE.update(running=True, error=None)
    try:
        episode = await asyncio.to_thread(generate_episode, day, refresh=refresh)
        logger.info("Podcast ready for %s (%.0fs).", day, episode.seconds)
        return episode
    except Exception as e:
        STATE["error"] = str(e)
        logger.error("Podcast failed: %s", e)
        notify_error("Morning podcast failed", e)
        raise
    finally:
        STATE["running"] = False


async def make_morning_podcast() -> None:
    """The scheduled job."""
    if not settings.podcast_enabled:
        return
    try:
        await run_podcast()
    except Exception:
        pass  # already logged and notified
