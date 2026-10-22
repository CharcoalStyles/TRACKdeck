"""
agent/writer.py
----------------
Split-model support: the small tool-calling model (LFM2.5 1.2B, "tool model")
drives every turn exactly as before; this module decides when a bigger local
model (settings.lmstudio_writer_model, "writer") should write what the user
actually reads, and does the writing.

One hook, called from agent/graph.py:

  * Rule A — finalize_reply(): after the tool model produces a turn's final
    (no-tool-call) reply, either keep its draft or have the writer redo it.
    Decided by decide() from mode, tools used, tool errors and draft length.

Everything fails soft: no writer model configured, wrong provider, timeout,
error, or invalid output -> the tool model's own text is used unchanged, and
the decision is recorded in utils/writer_log.py either way.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent.settings import settings
from utils import event_log, writer_log
from utils.datetime import format_now_human
from utils.llm_client import get_writer_llm

logger = logging.getLogger(__name__)

WRITER_TIMEOUT_SECONDS = 90
# A tool-model draft longer than this is assumed to be the tool model
# rambling (its prose is the weak spot) rather than a short confirmation.
CONFIRMATION_MAX_CHARS = 240
DATA_REPLY_MAX_CHARS = 500
# What the tool model sees of a writer-authored message in later turns —
# long writer prose in its history would pull it toward long prose itself.
TOOL_VIEW_MAX_CHARS = 200

WRITER_FLAG = "by_writer"

ALWAYS_WRITER_MODES = {"day_planning"}

# Tools whose result is a short fixed confirmation — the tool model's own
# one-line acknowledgement is fine for these.
CONFIRMATION_TOOLS = {
    "set_reminder", "set_timer", "cancel_reminder",
    "add_calendar_event", "delete_calendar_event", "update_calendar_event",
    "add_planning_task",
}
# Writes whose confirmation is built in code from the tool result, so the
# reply can only say what was actually saved.
TEMPLATE_TOOLS = {
    "add_calendar_event", "update_calendar_event", "move_calendar_event", "delete_calendar_event",
    "set_reminder", "set_timer", "cancel_reminder", "jot_note",
}
_RESULT_LEAD_RE = re.compile(r"^Event (?:added|updated|deleted) successfully\.(?: UID: \S+?\.)?\s*")
# Tools whose output the user needs turned into real prose.
PROSE_TOOLS = {"generate_schedule_blocks", "get_reflection_prompt", "fetch_webpage"}

MODE_GUIDANCE = {
    "day_planning": (
        "Summarise the resulting schedule plainly: what's planned and when, anything that didn't fit, "
        "and anything from recent reflections that shaped it. If the user gave arrangement guidance "
        "that couldn't be satisfied, say so."
    ),
}

WRITER_SYSTEM = """You write the final reply a user reads in a personal-assistant app. A smaller model has already chosen and run the tools; you are given what happened and its draft reply. You cannot call tools and must not claim to.

Rules:
- Say only what the conversation and tool results support. If a tool result shows a failure or "not found", tell the user plainly what didn't work — never imply success.
- Keep every concrete fact in the draft that the results support (names, dates, times, numbers). Drop anything the results don't support.
- Match length to the request: a confirmation is one or two sentences; an answer is as long as it needs to be and no longer.
- Tone: a little warmth is fine, kept in check — especially on heavier or personal topics. No reflexive validation or therapy-speak ("that takes incredible honesty"). Emoji rare. Don't open with filler like "Certainly!".
- If the user must make a choice or supply something missing, ask for it directly.
{style}{mode_guidance}
CURRENT DATE AND TIME: {now}

Reply with only the message to the user — no preamble, no quotes around it."""

VOICE_STYLE = (
    "- This reply is read as a short push notification after a voice command: plain text only "
    "(no markdown), at most three sentences, no follow-up question unless something is truly missing.\n"
)

_ERROR_PREFIXES = (
    "failed", "error", "couldn't", "could not", "no note found", "no pending reminder",
    "unable to", "invalid",
)


@dataclass
class TurnInfo:
    user_message: str = ""
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    results: list[tuple[str, str, bool]] = field(default_factory=list)  # (tool, content, is_error)
    steps: list[dict] = field(default_factory=list)  # ordered {name, args, result, error}, one per call

    @property
    def tool_names(self) -> list[str]:
        return [n for n, _ in self.tool_calls]

    @property
    def unresolved_errors(self) -> list[str]:
        """Tools whose latest result this turn was an error."""
        last: dict[str, bool] = {}
        for name, _content, err in self.results:
            last[name] = err
        return [n for n, e in last.items() if e]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in content if isinstance(p, (str, dict)))
    return str(content or "")


def is_error_result(msg: ToolMessage) -> bool:
    if getattr(msg, "status", None) == "error":
        return True
    return _text(msg.content).strip().lower().startswith(_ERROR_PREFIXES)


def current_turn(messages: list[BaseMessage]) -> TurnInfo:
    """Everything since the last human message."""
    start = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
    info = TurnInfo(user_message=_text(messages[start].content) if start >= 0 else "")
    call_names: dict[str, str] = {}
    steps: dict[str, dict] = {}
    for m in messages[start + 1:]:
        if m.type == "ai":
            for tc in getattr(m, "tool_calls", None) or []:
                info.tool_calls.append((tc["name"], tc.get("args") or {}))
                call_names[tc["id"]] = tc["name"]
                steps[tc["id"]] = {"name": tc["name"], "args": tc.get("args") or {}, "result": None, "error": None}
                info.steps.append(steps[tc["id"]])
        elif m.type == "tool":
            call_id = getattr(m, "tool_call_id", "")
            name = call_names.get(call_id, getattr(m, "name", None) or "tool")
            content, err = _text(m.content), is_error_result(m)
            info.results.append((name, content, err))
            if call_id in steps:
                steps[call_id]["result"], steps[call_id]["error"] = content, err
    return info


def decide(*, mode: str | None, one_shot: bool, info: TurnInfo, draft: str) -> tuple[bool, str]:
    """(use_writer, reason). Pure — Rule A."""
    if not draft.strip():
        return True, "empty_draft"
    if info.unresolved_errors:
        return True, "tool_error"
    if PROSE_TOOLS & set(info.tool_names):
        return True, "prose_tool"
    if mode in ALWAYS_WRITER_MODES:
        return True, f"mode:{mode}"
    if one_shot:
        return False, "one_shot"
    names = set(info.tool_names)
    if not names:
        return True, "conversation"
    limit = CONFIRMATION_MAX_CHARS if names <= CONFIRMATION_TOOLS else DATA_REPLY_MAX_CHARS
    if len(draft) <= limit:
        return False, "short_draft"
    return True, "long_draft"


def _is_lookup(name: str) -> bool:
    return name.startswith(("search_", "fetch_"))


_TIME_RE = re.compile(
    r"(?P<prefix>\b(?:at|from|around|by|until|till)\s+|@\s*)?\b(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>[ap]\.?m\b\.?)?",
    re.IGNORECASE,
)
_RELATIVE_RE = re.compile(
    r"\b(?:in|within)\s+(?:an?|\d+|a couple of|a few|half an?)\s*(?:hours?|minutes?|mins?)\b|\bnow\b|\bhalf an hour\b",
    re.IGNORECASE,
)


def _times_in(text: str, *, lenient: bool) -> set[tuple[int, int]]:
    """Clock times written in `text` as (hour24, minute). Bare numbers only
    count when `lenient` (the user's own words) and follow at/from/around/..."""
    found: set[tuple[int, int]] = set()
    low = text.lower()
    if "noon" in low:
        found.add((12, 0))
    if "midnight" in low:
        found.add((0, 0))
    for m in _TIME_RE.finditer(text):
        hour, minute, ap = int(m["h"]), int(m["m"] or 0), (m["ap"] or "").lower()
        if hour > 24 or minute > 59:
            continue
        has_colon = bool(m["m"])
        if not (ap or (has_colon and (lenient or ":" in m.group(0))) or (lenient and m["prefix"])):
            continue
        if ap:
            found.add((hour % 12 + (12 if ap.startswith("p") else 0), minute))
        elif hour >= 13 or hour == 0:
            found.add((hour % 24, minute))
        else:
            found.update({(hour, minute), ((hour % 12) + 12, minute)})
    return found


def _clock(hour: int, minute: int) -> str:
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def event_write_notes(info: TurnInfo) -> list[str]:
    """Plain-language caveats about a new event's saved details: a start time
    that neither the user nor a search result gave, and (after a search) a
    missing venue/description. Empty when nothing is doubtful."""
    adds = [a for n, a in info.tool_calls if n in _DETAIL_WRITE_TOOLS and n != "move_calendar_event"]
    if not adds or _RELATIVE_RE.search(info.user_message or ""):
        return []
    notes: list[str] = []
    backing = _times_in(info.user_message or "", lenient=True)
    for _name, content, is_err in info.results:
        if _is_lookup(_name) and not is_err:
            backing |= _times_in(content, lenient=False)
    for name, args in info.tool_calls:
        m = re.search(r"[ T](\d{1,2}):(\d{2})", str(args.get("start") or "")) if name == "add_calendar_event" else None
        if m and (int(m[1]), int(m[2])) not in backing:
            tail = "" if args.get("end") else ", and the end is just the one-hour default"
            notes.append(f"You didn't give a start time and I couldn't find one, so {_clock(int(m[1]), int(m[2]))} is a guess{tail}. Tell me the real time and I'll move it.")
            break
    new_events = [a for n, a in info.tool_calls if n == "add_calendar_event"]
    if new_events and any(_is_lookup(n) for n in info.tool_names) and not any(
        str(a.get("location") or "").strip() or str(a.get("description") or "").strip() for a in new_events
    ):
        notes.append("No venue or description was saved, so the event has only the title and time.")
    return notes


def template_reply(*, mode: str | None, info: TurnInfo) -> str | None:
    """Pure. The user-facing sentence(s) of this turn's successful calendar /
    reminder writes (plus caveats from `event_write_notes`), or None when the
    turn isn't only such writes and lookups (or any result lacks a sentence)."""
    if mode in ALWAYS_WRITER_MODES:
        return None
    names = set(info.tool_names)
    if not names & TEMPLATE_TOOLS or any(n not in TEMPLATE_TOOLS and not _is_lookup(n) for n in names):
        return None
    sentences: list[str] = []
    for tool_name, content, is_err in info.results:
        if is_err or tool_name not in TEMPLATE_TOOLS:
            continue
        sentence = _RESULT_LEAD_RE.sub("", content.strip()).strip()
        if not sentence:
            return None
        if sentence not in sentences:
            sentences.append(sentence)
    if not sentences:
        return None
    return "\n".join(sentences + event_write_notes(info))


_CLAIM_RE = re.compile(
    r"^\W*(?:(?:i(?:'ve| have)\s+)?(?:added|fixed|moved|deleted|removed|updated|cancel+ed|rescheduled|saved|created|trimmed|"
    r"changed|set)\b|done\b|all set\b)",
    re.IGNORECASE,
)
_READ_ONLY_PREFIXES = ("get_", "list_", "search_", "read_", "fetch_")
NO_CHANGE_REPLY = "I haven't changed anything yet. Tell me what you'd like and I'll do it."


def unsupported_claim(draft: str, info: TurnInfo) -> bool:
    """True when the reply opens by claiming a change but no tool that could
    make one succeeded this turn."""
    if not _CLAIM_RE.match(draft or "") or info.unresolved_errors:
        return False
    for name, _content, is_err in info.results:
        if not is_err and (name.startswith("get_or_create_") or not name.startswith(_READ_ONLY_PREFIXES)):
            return False
    return True


_DETAIL_CLAIM_RE = re.compile(
    r"\b(?:double[- ]?check(?:ed)?|verified|looked (?:it )?up|found|checked (?:their|the) (?:website|site))\b[^.!?\n]*"
    r"\b(?:details?|venue|address|hours|website)\b|\b(?:more|extra|further) details\b",
    re.IGNORECASE,
)
_DETAIL_WRITE_TOOLS = {"add_calendar_event", "update_calendar_event", "move_calendar_event"}


def unbacked_detail_claim(draft: str, info: TurnInfo) -> str | None:
    """Replacement reply when the draft says it found/added extra event details
    but no successful calendar write this turn carried a location or
    description; else None."""
    if not _DETAIL_CLAIM_RE.search(draft or ""):
        return None
    writes = [(n, a) for n, a in info.tool_calls if n in _DETAIL_WRITE_TOOLS]
    if not writes or any(str(a.get("location") or "").strip() or str(a.get("description") or "").strip() for _, a in writes):
        return None
    sentences: list[str] = []
    for tool_name, content, is_err in info.results:
        if is_err or tool_name not in _DETAIL_WRITE_TOOLS:
            continue
        sentence = _RESULT_LEAD_RE.sub("", content.strip()).strip()
        if sentence and sentence not in sentences:
            sentences.append(sentence)
    if not sentences:
        return None
    return "\n".join(sentences) + "\nI didn't add a venue or description, so the event has only the title and time."


def writer_enabled() -> bool:
    return bool(settings.lmstudio_writer_model)


def shorten_for_tool_model(text: str, limit: int = TOOL_VIEW_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    m = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
    if m >= limit // 3:
        cut = cut[: m + 1]
    return cut.rstrip() + " …"


def tool_model_view(messages: list[BaseMessage]) -> list[BaseMessage]:
    """History as the tool model should see it: writer-authored replies shortened."""
    out = []
    for m in messages:
        if m.type == "ai" and (m.additional_kwargs or {}).get(WRITER_FLAG) and not getattr(m, "tool_calls", None):
            short = shorten_for_tool_model(_text(m.content))
            if short != _text(m.content):
                m = m.model_copy(update={"content": short})
        out.append(m)
    return out


_semaphore = asyncio.Semaphore(1)


async def _invoke(messages: list[BaseMessage], temperature: float, timeout: float) -> str:
    llm = get_writer_llm(temperature)
    async with _semaphore:
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
    return _clean(_text(response.content))


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(reply|response|message)\s*:\s*", "", text, flags=re.I)
    if len(text) > 1 and text[0] == text[-1] == '"' and '"' not in text[1:-1]:
        text = text[1:-1].strip()
    return text


def _conversation_for_writer(messages: list[BaseMessage], max_chars: int = 6000) -> list[BaseMessage]:
    """Prior turns (before the current human message) as plain user/assistant text."""
    start = max((i for i, m in enumerate(messages) if m.type == "human"), default=0)
    out: list[BaseMessage] = []
    for m in messages[:start]:
        text = _text(m.content).strip()
        if not text:
            continue
        if m.type == "human":
            out.append(HumanMessage(content=text))
        elif m.type == "ai" and not getattr(m, "tool_calls", None):
            out.append(AIMessage(content=text))
    while out and out[0].type != "human":
        out.pop(0)
    total = 0
    kept: list[BaseMessage] = []
    for m in reversed(out):
        total += len(m.content)
        if total > max_chars and kept:
            break
        kept.append(m)
    kept.reverse()
    while kept and kept[0].type != "human":
        kept.pop(0)
    return kept


def _render_work(info: TurnInfo, per_result: int = 3000, total: int = 9000) -> str:
    if not info.tool_calls:
        return "(no tools were used this turn)"
    lines, used = [], 0
    results_by_order = list(info.results)
    for i, (name, args) in enumerate(info.tool_calls):
        arg_text = json.dumps(args, ensure_ascii=False)
        if len(arg_text) > 400:
            arg_text = arg_text[:400] + "…"
        lines.append(f"- Called {name}({arg_text})")
        if i < len(results_by_order):
            _n, content, err = results_by_order[i]
            content = content if len(content) <= per_result else content[:per_result] + "…[truncated]"
            if used + len(content) > total:
                content = "[omitted for length]"
            used += len(content)
            lines.append(f"  Result{' (ERROR)' if err else ''}: {content}")
    return "\n".join(lines)


async def rewrite_reply(
    messages: list[BaseMessage],
    *,
    draft: str,
    mode: str | None = None,
    one_shot: bool = False,
    timeout: float = WRITER_TIMEOUT_SECONDS,
) -> str:
    """Ask the writer model for the turn's final reply. Raises on failure."""
    info = current_turn(messages)
    guidance = MODE_GUIDANCE.get(mode or "", "")
    system = WRITER_SYSTEM.format(
        style=VOICE_STYLE if one_shot else "",
        mode_guidance=f"- {guidance}\n" if guidance else "",
        now=format_now_human(settings.zoneinfo()),
    )
    final = (
        f"The user's latest message:\n{info.user_message}\n\n"
        f"What the assistant did this turn:\n{_render_work(info)}\n\n"
        f"Draft reply from the smaller model (may be clumsy, too long, or wrong about failures):\n"
        f"{draft.strip() or '(empty)'}\n\n"
        "Write the reply the user should read."
    )
    out = await _invoke(
        [SystemMessage(content=system), *_conversation_for_writer(messages), HumanMessage(content=final)],
        temperature=0.5,
        timeout=timeout,
    )
    if not out:
        raise ValueError("writer returned empty text")
    if "<|" in out or '"tool_call' in out or out.lstrip().startswith("{\"name\""):
        raise ValueError("writer output looks like tool-call syntax")
    return out


async def finalize_reply(
    messages: list[BaseMessage],
    *,
    draft: str,
    thread_id: str | None,
    mode: str | None,
    one_shot: bool,
) -> str | None:
    """Rule A. Returns replacement text, or None to keep the tool model's draft."""
    info = current_turn(messages)
    templated = template_reply(mode=mode, info=info)
    if templated:
        await _log(thread_id=thread_id, kind="reply", mode=mode, reason="calendar_reminder_write",
                   tools=info.tool_names, draft=draft, route="template", model=None, final=templated)
        return templated
    unbacked = unbacked_detail_claim(draft, info)
    if unbacked:
        await _log(thread_id=thread_id, kind="reply", mode=mode, reason="unbacked_detail_claim",
                   tools=info.tool_names, draft=draft, route="template", model=None, final=unbacked)
        return unbacked
    if unsupported_claim(draft, info):
        await _log(thread_id=thread_id, kind="reply", mode=mode, reason="unsupported_claim",
                   tools=info.tool_names, draft=draft, route="template", model=None, final=NO_CHANGE_REPLY)
        return NO_CHANGE_REPLY
    if not writer_enabled():
        return None
    use_writer, reason = decide(mode=mode, one_shot=one_shot, info=info, draft=draft)
    model = settings.lmstudio_writer_model
    log_kwargs = dict(thread_id=thread_id, kind="reply", mode=mode,
                      reason=reason, tools=info.tool_names, draft=draft)
    if not use_writer:
        await _log(route="tool_model", model=None, final=draft, **log_kwargs)
        return None
    started = time.monotonic()
    try:
        text = await rewrite_reply(messages, draft=draft, mode=mode, one_shot=one_shot)
    except Exception as e:  # noqa: BLE001 — any writer failure must fall back to the draft
        logger.warning("writer failed (%s), keeping tool-model draft: %r", reason, e)
        await _log(route="fallback", model=model, final=draft, latency_ms=_ms(started),
                   error=f"{type(e).__name__}: {e}", **log_kwargs)
        return None
    await _log(route="writer", model=model, final=text, latency_ms=_ms(started), **log_kwargs)
    return text


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)


async def _log(**kwargs) -> None:
    if kwargs.get("kind") == "reply" and kwargs.get("route"):
        event_log.note_reply_route(kwargs["route"])
    try:
        await asyncio.to_thread(writer_log.log_writer, **kwargs)
    except Exception:  # noqa: BLE001 — logging must never break a turn
        logger.exception("writer_log write failed")
