from agent.keywords import generate_keyword, match_keyword_prefix


def test_generate_keyword_avoids_collisions():
    existing = {"Copper Wolf"}
    for _ in range(50):
        keyword = generate_keyword(existing)
        assert keyword not in existing


def test_match_keyword_prefix_tolerates_single_word_mishearing():
    # Simulates Whisper mishearing "Wolf" as "Wolfe" — still one clean
    # keyword, so the joined-phrase and per-word checks agree here.
    matched, remaining = match_keyword_prefix(
        "Copper Wolfe actually make that 3pm", ["Copper Wolf"]
    )
    assert matched == "Copper Wolf"
    assert remaining == "actually make that 3pm"


def test_match_keyword_prefix_rejects_unrelated_phrase_that_scores_high_joined():
    # "silver spoon" vs "Silver Swan" scores above MATCH_THRESHOLD as a
    # joined string even though "spoon" isn't a close match for "Swan" on
    # its own — this is the exact false-positive the per-word min() ratio
    # (agent/keywords.py) was added to reject.
    matched, remaining = match_keyword_prefix(
        "silver spoon please help me", ["Silver Swan"]
    )
    assert matched is None
    assert remaining == "silver spoon please help me"


def test_match_keyword_prefix_empty_remainder_on_keyword_only_utterance():
    # An accidental double button-press with nothing said beyond the
    # callsign — callers treat "" as a no-op reconnect, not a real message.
    matched, remaining = match_keyword_prefix("Copper Wolf", ["Copper Wolf"])
    assert matched == "Copper Wolf"
    assert remaining == ""


def test_match_keyword_prefix_no_match_falls_back_unchanged():
    matched, remaining = match_keyword_prefix(
        "hello there friend", ["Copper Wolf"]
    )
    assert matched is None
    assert remaining == "hello there friend"


def test_match_keyword_prefix_single_word_input_never_matches():
    matched, remaining = match_keyword_prefix("Copper", ["Copper Wolf"])
    assert matched is None
    assert remaining == "Copper"
