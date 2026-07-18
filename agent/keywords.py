"""
agent/keywords.py
------------------
Generates memorable two-word keywords for addressable threads, and
fuzzy-matches a spoken/transcribed prefix against the set of currently
active ones.

No LLM call involved — this is deliberately a cheap, deterministic
wordlist pick (same pattern Docker/Heroku use for container names), not
something worth spending a generation on. Matching uses stdlib difflib
rather than pulling in a fuzzy-matching dependency; a two-word phrase is
short enough that SequenceMatcher's ratio is a fine similarity measure,
and this needs to tolerate Whisper mishearing a word, not do anything
more sophisticated than that.

Words are chosen to be distinctive and unlikely to appear in ordinary
commands ("Copper Wolf" rather than "Quick Light"), and matching only
ever looks at the first two words of an utterance — a keyword is meant
to be spoken as a prefix/callsign ("Copper Wolf, actually make that
3pm"), not searched for anywhere in the sentence.
"""
from __future__ import annotations

import random
from difflib import SequenceMatcher

MATCH_THRESHOLD = 0.75

ADJECTIVES = [
    "Copper", "Amber", "Violet", "Crimson", "Emerald", "Silver", "Golden",
    "Obsidian", "Ivory", "Cobalt", "Scarlet", "Jade", "Indigo", "Bronze",
    "Pearl", "Onyx", "Rusty", "Frosted", "Velvet", "Marble", "Granite",
    "Sapphire", "Ruby", "Slate", "Dusty", "Ember", "Misty", "Stormy",
    "Sunny", "Shadow",
]

NOUNS = [
    "Wolf", "Falcon", "Otter", "Badger", "Heron", "Lynx", "Raven", "Fox",
    "Hawk", "Stag", "Owl", "Bear", "Panther", "Eagle", "Wren", "Marten",
    "Ferret", "Osprey", "Kestrel", "Bison", "Elk", "Ibis", "Crane",
    "Marlin", "Sable", "Puma", "Cougar", "Finch", "Swan", "Heron",
]


def generate_keyword(existing: "dict | set") -> str:
    """Pick an unused ADJECTIVE NOUN phrase. `existing` is anything
    supporting `in` (a dict or set of currently active keywords)."""
    for _ in range(50):
        phrase = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)}"
        if phrase not in existing:
            return phrase
    # Astronomically unlikely with ~900 combinations and a handful of
    # concurrent threads, but never return a colliding keyword.
    return f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)} {random.randint(2, 99)}"


def match_keyword_prefix(text: str, active_keywords) -> tuple[str | None, str]:
    """
    Check whether `text` opens with something close to one of
    `active_keywords` (an iterable of keyword strings). Returns
    (matched_keyword_or_None, remaining_text_with_prefix_stripped).

    If nothing matches with real confidence, returns (None, text)
    unchanged — callers should fall back to normal thread resolution.
    """
    words = text.strip().split()
    if len(words) < 2:
        return None, text

    candidate = " ".join(words[:2]).strip(".,!?").lower()

    best_keyword = None
    best_ratio = 0.0
    for keyword in active_keywords:
        ratio = SequenceMatcher(None, candidate, keyword.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_keyword = keyword

    if best_keyword is not None and best_ratio >= MATCH_THRESHOLD:
        remaining = " ".join(words[2:]).strip()
        remaining = remaining.lstrip(",").strip()
        return best_keyword, (remaining or text)

    return None, text
