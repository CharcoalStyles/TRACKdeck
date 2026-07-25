import pytest

from agent.runtime import SESSION_TIMEOUT_SECONDS, app_state, resolve_thread


@pytest.fixture(autouse=True)
def clean_app_state():
    app_state.threads = {}
    app_state.keywords = {}
    app_state.default_thread_id = None
    app_state.default_last_activity = 0.0
    yield
    app_state.threads = {}
    app_state.keywords = {}
    app_state.default_thread_id = None
    app_state.default_last_activity = 0.0


def _set_clock(monkeypatch, now: float):
    monkeypatch.setattr("agent.runtime.time.time", lambda: now)


def test_resolve_thread_starts_a_new_thread_when_none_exists(monkeypatch):
    _set_clock(monkeypatch, 1000.0)
    thread_id, keyword, cleaned_text = resolve_thread("what's on my calendar today")

    assert cleaned_text == "what's on my calendar today"
    assert thread_id == app_state.default_thread_id
    assert app_state.keywords[keyword] == thread_id


def test_resolve_thread_continues_recent_default_thread(monkeypatch):
    _set_clock(monkeypatch, 1000.0)
    first_id, _, _ = resolve_thread("first message")

    _set_clock(monkeypatch, 1000.0 + SESSION_TIMEOUT_SECONDS - 1)
    second_id, _, _ = resolve_thread("second message")

    assert second_id == first_id
    assert len(app_state.threads) == 1


def test_resolve_thread_starts_new_thread_after_session_timeout(monkeypatch):
    _set_clock(monkeypatch, 1000.0)
    first_id, _, _ = resolve_thread("first message")

    _set_clock(monkeypatch, 1000.0 + SESSION_TIMEOUT_SECONDS + 1)
    second_id, _, _ = resolve_thread("second message")

    assert second_id != first_id
    assert len(app_state.threads) == 2


def test_resolve_thread_keyword_prefix_reopens_thread_past_session_timeout(monkeypatch):
    _set_clock(monkeypatch, 1000.0)
    old_id, old_keyword, _ = resolve_thread("remember this project detail")

    # Long past SESSION_TIMEOUT_SECONDS, and a different default thread has
    # since become active — keyword addressing must still win over recency.
    _set_clock(monkeypatch, 1000.0 + SESSION_TIMEOUT_SECONDS + 1)
    resolve_thread("an unrelated new conversation")
    assert app_state.default_thread_id != old_id

    _set_clock(monkeypatch, 1000.0 + 2 * SESSION_TIMEOUT_SECONDS)
    thread_id, keyword, cleaned_text = resolve_thread(f"{old_keyword}, actually make that 3pm")

    assert thread_id == old_id
    assert keyword == old_keyword
    assert cleaned_text == "actually make that 3pm"
    # Reconnecting via keyword should also promote it back to the default.
    assert app_state.default_thread_id == old_id


def test_resolve_thread_keyword_pointing_at_cleared_thread_falls_back(monkeypatch):
    # Shouldn't normally happen (keyword and thread are cleared together),
    # but a stale mapping must fall back to normal resolution rather than
    # raising.
    _set_clock(monkeypatch, 1000.0)
    app_state.keywords["Ghost Keyword"] = "thread_that_no_longer_exists"

    thread_id, keyword, cleaned_text = resolve_thread("Ghost Keyword, do something")

    assert thread_id != "thread_that_no_longer_exists"
    assert cleaned_text == "Ghost Keyword, do something"
