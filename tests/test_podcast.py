import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from agent import scheduler
from agent.settings import settings
from jobs import morning, podcast
from utils import morning_context, news, tts

DAY = date(2026, 11, 1)  # a Sunday

FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Lovely new cafe opens in Braddon</title><link>https://x.test/1</link>
<description>&lt;p&gt;Coffee &amp;amp; cake.&lt;/p&gt;</description><pubDate>{fresh}</pubDate></item>
<item><title>Man charged after stabbing</title><link>https://x.test/2</link>
<description>grim</description><pubDate>{fresh}</pubDate></item>
<item><title>Ancient story</title><link>https://x.test/3</link>
<description>old</description><pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>
</channel></rss>"""


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("EVENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "timezone", "UTC")
    monkeypatch.setattr(settings, "public_base_url", "https://pa.example.com/")
    monkeypatch.setattr(settings, "podcast_enabled", True)
    monkeypatch.setattr(morning_context.news, "fetch_headlines", lambda: [])
    monkeypatch.setattr(morning_context.news, "fetch_on_this_day", lambda day: [])
    monkeypatch.setattr(morning_context, "render_weather_extras", lambda day: "")
    for name in ("render_calendar", "render_reminders", "render_forecast", "render_open_captures", "render_plan_window"):
        monkeypatch.setattr(morning_context.day_context, name, lambda *a: "")
    morning_context._cache.clear()
    podcast.STATE.update(running=False, error=None)
    return tmp_path


def test_feed_parsing_drops_old_and_dull_stories():
    now = datetime.now(timezone.utc)
    fresh = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = news.parse_feed(FEED.format(fresh=fresh), "Test", now)
    assert [i["title"] for i in items] == ["Lovely new cafe opens in Braddon", "Man charged after stabbing"]
    assert items[0]["summary"] == "Coffee & cake."
    assert [i["title"] for i in items if not news.is_dull(i["title"], i["summary"])] == [items[0]["title"]]


def test_headlines_fail_soft_and_interleave(monkeypatch):
    class Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    fresh = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    def fake_get(url, **kw):
        if "riotact" in url:
            raise RuntimeError("down")
        return Resp(FEED.format(fresh=fresh))

    monkeypatch.setattr(news.requests, "get", fake_get)
    out = news.fetch_headlines()
    assert [h["source"] for h in out] == ["The Canberra Times"]
    assert out[0]["link"] == "https://x.test/1" and "published" not in out[0]


def test_on_this_day_is_deterministic_and_filters(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"selected": [{"year": 1900 + i, "text": f"Something fun {i}"} for i in range(8)]
                    + [{"year": 1914, "text": "A war began"}]}

    monkeypatch.setattr(news.requests, "get", lambda *a, **k: Resp())
    first = news.fetch_on_this_day(DAY)
    assert first == news.fetch_on_this_day(DAY) and len(first) == 2
    assert all("war" not in e["text"] for e in first)
    monkeypatch.setattr(news.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert news.fetch_on_this_day(DAY) == []


def test_parse_script_handles_tags_continuations_and_untagged():
    turns = podcast.parse_script("HOST: Morning!\n**CO:** Hi there.\nAnd more.\n\nhost: Bye")
    assert turns == [("HOST", "Morning!"), ("CO", "Hi there. And more."), ("HOST", "Bye")]
    assert podcast.parse_script("Just narration.") == [("HOST", "Just narration.")]


def test_spoken_cleans_times_units_and_links():
    assert podcast.spoken("At 13:10 it is 24 C, 30% rain, see https://x.test/a **now**") == (
        "At 1:10 PM it is 24 degrees, 30 percent rain, see now"
    )
    assert podcast.spoken("Start at 09:00 and 00:30") == "Start at 9 AM and 12:30 AM"


def test_voice_pairs_rotate_by_day_and_are_stable():
    seen = {tuple(podcast.pick_voices(DAY + timedelta(days=i)).values()) for i in range(len(podcast.VOICE_PAIRS))}
    assert len(seen) == len(podcast.VOICE_PAIRS)
    assert podcast.pick_voices(DAY) == podcast.pick_voices(DAY)


def test_podcast_job_runs_before_morning(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "UTC")
    monkeypatch.setattr(settings, "morning_time", "05:25")
    fields = {f.name: str(f) for f in podcast_trigger_fields()}
    assert fields["hour"] == "5" and fields["minute"] == "0"
    monkeypatch.setattr(settings, "morning_time", "00:10")
    fields = {f.name: str(f) for f in podcast_trigger_fields()}
    assert fields["hour"] == "0" and fields["minute"] == "0"


def podcast_trigger_fields():
    return scheduler.podcast_trigger().fields


def test_generate_episode_writes_mp3_and_script(env, monkeypatch):
    morning_context._cache[DAY] = morning_context.MorningContext(
        day=DAY,
        calendar="- Sun 01 Nov 13:10 Dentist",
        headlines=[{"title": "Cafe opens", "summary": "Nice.", "link": "https://x.test/1", "source": "RiotACT"}],
        on_this_day=[{"year": 1950, "text": "Something fun"}],
    )
    prompts, rendered = [], []
    monkeypatch.setattr(podcast, "write", lambda p, **k: prompts.append(p) or "HOST: Good morning.\nCO: Dentist at 13:10.")
    monkeypatch.setattr(
        podcast.tts, "render_mp3",
        lambda turns, voices, out, title: rendered.append((turns, voices, title)) or out.parent.mkdir(parents=True, exist_ok=True) or out.write_bytes(b"mp3") or 12.5,
    )
    episode = podcast.generate_episode(DAY)
    assert "Dentist" in prompts[0] and "[RiotACT] Cafe opens: Nice." in prompts[0] and "1950: Something fun" in prompts[0]
    assert "https://x.test/1" not in prompts[0]
    # Empty sections are left out entirely, topics and material both.
    assert "Forecast" not in prompts[0] and "Captures still open" not in prompts[0]
    assert "the weather" not in prompts[0] and "one \"on this day\" item" in prompts[0]
    turns, voices, title = rendered[0]
    assert turns == [("HOST", "Good morning."), ("CO", "Dentist at 1:10 PM.")]
    assert voices == podcast.pick_voices(DAY) and "Sunday 01 November 2026" in title
    assert episode.mp3.read_bytes() == b"mp3" and "Good morning." in episode.script.read_text()
    assert podcast.episode_exists(DAY)


def test_failed_run_records_error_and_notifies(env, monkeypatch):
    notified = []
    monkeypatch.setattr(podcast, "notify_error", lambda ctx, e: notified.append(ctx))
    monkeypatch.setattr(podcast, "generate_episode", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LM down")))
    with pytest.raises(RuntimeError):
        asyncio.run(podcast.run_podcast(DAY))
    assert podcast.STATE == {"running": False, "error": "LM down"}
    assert notified == ["Morning podcast failed"]
    monkeypatch.setattr(settings, "podcast_enabled", False)
    asyncio.run(podcast.make_morning_podcast())  # disabled: no run, no raise


def test_old_episodes_are_pruned(env):
    podcast.podcast_dir().mkdir(parents=True)
    for i in range(1, 6):
        d = date(2026, 10, i)
        podcast.mp3_path(d).write_bytes(b"x")
        podcast.script_path(d).write_text("s")
    podcast.prune_old_episodes(keep=2)
    assert sorted(p.name for p in podcast.podcast_dir().iterdir()) == [
        "2026-10-04.md", "2026-10-04.mp3", "2026-10-05.md", "2026-10-05.mp3",
    ]


def test_morning_message_adds_headlines_and_link_only_when_available(env, monkeypatch):
    morning_context._cache[DAY] = morning_context.MorningContext(
        day=DAY, headlines=[{"title": "Cafe opens", "summary": "", "link": "https://x.test/1", "source": "RiotACT"}]
    )
    monkeypatch.setattr(morning, "write", lambda p, **k: "Good morning text")
    text = morning.compose_morning_message(DAY)
    assert "Canberra headlines:\n- Cafe opens (RiotACT)\n  https://x.test/1" in text
    assert "Listen" not in text  # no episode yet
    podcast.podcast_dir().mkdir(parents=True)
    podcast.mp3_path(DAY).write_bytes(b"x")
    text = morning.compose_morning_message(DAY)
    assert text.endswith("Listen to this morning's podcast: https://pa.example.com/podcast")


def test_routes_list_serve_and_guard(env):
    from fastapi import HTTPException

    from routes import podcast as routes

    assert asyncio.run(routes.list_podcasts(None))["episodes"] == []
    podcast.podcast_dir().mkdir(parents=True)
    podcast.mp3_path(DAY).write_bytes(b"x")
    podcast.script_path(DAY).write_text("# t\n\nHOST: hi")
    listing = asyncio.run(routes.list_podcasts(None))
    assert listing["episodes"] == [{"date": "2026-11-01", "has_script": True}] and not listing["running"]
    assert asyncio.run(routes.get_podcast_script("2026-11-01", None))["script"].endswith("hi")
    assert asyncio.run(routes.get_podcast_audio("2026-11-01", None)).path == podcast.mp3_path(DAY)
    for bad in ("../etc", "2026-11-02", "nonsense"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(routes.get_podcast_audio(bad, None))
        assert e.value.status_code == 404
    podcast.STATE["running"] = True
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.run_podcast_now(None))
    assert e.value.status_code == 409


def test_tts_falls_back_when_a_voice_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "MODEL_DIR", tmp_path)
    assert tts.resolve_voice("nope") == tts.FALLBACK_VOICE
    (tmp_path / "here.onnx").write_bytes(b"")
    assert tts.resolve_voice("here") == "here"


def test_opinion_pieces_are_filtered_like_dull_ones():
    for title in ("Don't just blame the oil prices. Here's the real failure", "Why we must act now",
                  "Israel is just the start. This is a crucial warning"):
        assert news.is_dull(title)
    assert not news.is_dull("Beers + brisket = a summer collaboration worth celebrating")


def test_story_without_summary_is_marked_so_the_writer_adds_nothing():
    ctx = morning_context.MorningContext(
        day=DAY, headlines=[{"title": "Cafe opens", "summary": "", "link": "l", "source": "RiotACT"}]
    )
    assert "- [RiotACT] Cafe opens: (no summary)" in podcast.build_prompt(ctx)


def test_uv_label_bands():
    assert [morning_context.uv_label(i) for i in (1, 4, 7, 8, 10, 11)] == [
        "low", "moderate", "high", "very high", "very high", "extreme"
    ]
