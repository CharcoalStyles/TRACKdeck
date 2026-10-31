"""
utils/news.py
--------------
Canberra headlines from two RSS feeds and a Wikipedia "on this day" item, for
the morning podcast and email. Plain HTTP and stdlib XML: no search tool, no
model. Every fetch fails soft (an empty list), so a dead feed never stops the
morning.
"""
from __future__ import annotations

import html
import logging
import random
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

FEEDS = {
    "RiotACT": "https://the-riotact.com/feed",
    "The Canberra Times": "https://www.canberratimes.com.au/rss.xml",
}
USER_AGENT = "trackdeck/2 (personal morning briefing)"
MAX_AGE = timedelta(hours=40)
HEADLINES_PER_SOURCE = 3
ON_THIS_DAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{month:02d}/{day:02d}"

# A light morning show: drop stories about crime, courts and death.
DULL = re.compile(
    r"\b(stabb\w*|murder\w*|kill\w*|dead|death|dies|died|die|suicide|jail\w*|court|coroner|"
    r"charged|arrest\w*|assault\w*|rape\w*|abuse\w*|crash\w*|fatal\w*|police|shoot\w*|"
    r"overdose\w*|drug\w*|sentenc\w*|inquest|war|attack\w*|terror\w*|bomb\w*|missing|"
    r"cancer|funeral|tragedy|tragic|victim\w*)\b",
    re.IGNORECASE,
)


# Commentary pieces: the show reads news, not opinion.
OPINION = re.compile(
    r"\b(opinion|editorial|analysis|should|must|we need|why we|why you|here.s why|here.s the real|"
    r"warning|don.t just|the real failure|is just the start|wake.up call)\b",
    re.IGNORECASE,
)


def is_dull(*texts: str) -> bool:
    return any(DULL.search(t or "") or OPINION.search(t or "") for t in texts)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_feed(xml_text: str, source: str, now: datetime | None = None) -> list[dict]:
    """Items newer than MAX_AGE, newest first: title, summary, link, source."""
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = None
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
        if published and now - published > MAX_AGE:
            continue
        items.append(
            {
                "title": title,
                "summary": _clean(item.findtext("description"))[:300],
                "link": link,
                "source": source,
                "published": published,
            }
        )
    items.sort(key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items


def fetch_headlines() -> list[dict]:
    """Up to HEADLINES_PER_SOURCE light stories per feed, interleaved."""
    per_source = []
    for source, url in FEEDS.items():
        try:
            response = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            items = [i for i in parse_feed(response.text, source) if not is_dull(i["title"], i["summary"])]
            per_source.append(items[:HEADLINES_PER_SOURCE])
        except Exception as e:
            logger.warning("Headline feed %s failed: %s", source, e)
    out = []
    for group in zip(*[g + [None] * (HEADLINES_PER_SOURCE - len(g)) for g in per_source]):
        out.extend(i for i in group if i)
    return [{k: v for k, v in i.items() if k != "published"} for i in out]


def fetch_on_this_day(day: date, count: int = 2) -> list[dict]:
    """A couple of Wikipedia "selected" events for the date, picked
    deterministically per day so a re-run gives the same ones."""
    try:
        response = requests.get(
            ON_THIS_DAY_URL.format(month=day.month, day=day.day),
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        events = [e for e in response.json().get("selected", []) if e.get("text") and not is_dull(e["text"])]
    except Exception as e:
        logger.warning("On-this-day fetch failed: %s", e)
        return []
    chosen = random.Random(day.toordinal()).sample(events, min(count, len(events)))
    return [{"year": e.get("year"), "text": _clean(e["text"])} for e in chosen]
