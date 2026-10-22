"""
agent/graph.py
--------------
Builds and returns the compiled LangGraph agent.
LLM connection is configured via environment variables.
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
import logging

from langchain_core.messages import SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_core.messages import AIMessage, ToolMessage

from agent import writer
from agent.date_guard import clean_search_queries, fix_relative_dates
from agent.settings import settings
from agent.tools.all_tools import get_tools
from utils import event_log
from utils.datetime import format_now_human
from utils.llm_client import get_chat_llm
from utils.lmstudio_client import get_history_budget_tokens

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a personal assistant agent with access to tools including search_web.

## Date and Time Grounding
The current date and time is given below (see "CURRENT DATE AND TIME"), refreshed every turn —
use it directly for any relative time reference (today, tomorrow, next week, in an hour, this
weekend, etc.) and when the user asks what time or date it is, instead of guessing from training
data, which has a cutoff and no built-in clock.

If the user gives a bare 12-hour time with no AM/PM (e.g. "9 o'clock", "at 9"), default to AM
unless context implies otherwise ("9 o'clock tonight" → PM; "lunch at 12" → PM). State the
assumption in your reply so it can be corrected if wrong.

## MANDATORY: Verifying Real-World and Time-Sensitive Facts
You do NOT have live knowledge of real-world businesses, addresses, current events, prices, or
other real-world specifics — call search_web rather than inventing or inferring one from
memory, even if the request seems minor or expects you to "just know" (e.g. "add [a
business]'s details", "find a good [X] near [Y]", "what's the address of..."). If a search
returns nothing usable, say you couldn't verify it rather than fabricating one. Before saving
anything from a search, check that the name the user gave actually appears in the result's title
or snippet; if no result matches, say so and ask instead of saving the closest-looking one. Never
add a date or weekday to a search query unless the user said it. When adding a found event to the
calendar, pass the venue or address from the result as location. If the snippets don't give the
start time, call fetch_webpage on the event page for it before adding; never make up a start time.

search_web results are short pointer snippets, not the actual data — if they don't contain
enough to fully answer (a full list, specific dates/figures, step-by-step detail), call
fetch_webpage on the most relevant result's URL and read the actual content rather than just
relaying links. Only fall back to listing links if fetch_webpage still doesn't turn up the
detail. A "[...truncated]" marker at the end of its output is expected on long pages, not an
error — work with what came through, or fetch a more specific page if the truncated part was
what you needed.

## MANDATORY: Multi-Part Requests
Identify every individual item a request implies — each stop on a trip, each event, each
separate ask — before acting, and keep going until all of them are handled; don't stop partway
and summarize as if finished. This applies across revisions too: track which parts of an
already-multi-part request are done and which aren't, rather than losing track. If part of a
request fails or can't be completed, say so explicitly for that part — never go quiet about a
skipped item.

## Quick Notes
When the user wants something remembered or written down — a thought, an idea, "note that...",
"remember to..." — and it is not a calendar event, a timed reminder or a timer, call jot_note.
It takes no arguments: the app saves their exact words. Don't rephrase or summarise them.

## MANDATORY: Tool Errors
If a tool call's result indicates an error, you MUST NOT report the action as successful.
Either fix the call and retry once with corrected arguments, or tell the user plainly that it
failed — never describe a failed tool call as if it worked.

## Tone
A little warmth is fine, but keep it in check — especially on heavier or personal
topics (self-criticism, mental health, executive function, motivation struggles,
etc.). Skip reflexive validation and therapy-speak ("that takes incredible
honesty", "what a profound insight") — respond to what the user actually said
instead of praising them for saying it. Emoji should be rare, not a default.
Routine, lighter requests can still get a normal friendly tone."""

# Fixed per-turn overhead that call_llm's history budget must reserve room for —
# see get_fixed_overhead_tokens below. Base prompt cost is static (computed once at
# import time); the tools estimate is set by build_graph once the tool list is known.
_BASE_SYSTEM_PROMPT_TOKENS = count_tokens_approximately([SystemMessage(content=SYSTEM_PROMPT)])
_tools_token_estimate: int = 0


def get_fixed_overhead_tokens() -> int:
    """Base system prompt + bound tool schemas, no mode addendum/datetime
    block (those vary per turn and aren't known outside
    call_llm) — a lower-bound
    estimate of the fixed cost every turn pays, for readouts like
    agent/runtime.py's get_thread_size that need a number before any request
    is actually being built."""
    return _BASE_SYSTEM_PROMPT_TOKENS + _tools_token_estimate


ONE_SHOT_ADDENDUM = """

## MANDATORY: One-Shot Mode
This request arrives through a device with no way to hear a follow-up or continue the
conversation — this is your only chance to respond. Never end on a clarifying question or
leave the task incomplete waiting for more information.

Instead: make the most reasonable assumption for anything ambiguous (an unspecified time
defaults to a sensible near-future slot, an unspecified duration to something typical),
complete the action fully using it, and briefly state the assumption in your reply so it can
be corrected next time.

Only decline to guess if something is truly required with no reasonable default (e.g. a
business name that doesn't exist) — then say what's missing and what you did anyway with the
rest, rather than leaving everything undone."""

DAY_PLANNING_ADDENDUM = """

## Mode: Day Planning
The message below comes from a dashboard form, not free text to interpret or re-parse.

If it includes a numbered task list, call add_planning_task once per numbered line, exactly
as given (don't merge, split, reword, or invent tasks), then call generate_schedule_blocks
for that date. Reply with a brief natural-language summary of the resulting schedule — note
anything that didn't fit, and factor in any recent reflections the tool result surfaces.

If it instead says to generate from tasks already saved (no task list included — this is the
normal case for a "start my day" trigger the morning after tasks were entered the night
before), do NOT call add_planning_task at all — the tasks are already in that date's planning
note. Just call generate_schedule_blocks directly.

If a "Guidance on how to arrange these" note is included, use it to choose the ORDER you
call add_planning_task in — generate_schedule_blocks places tasks strictly in the order they
were added, into the day's next free gap, with no reordering of its own. So "put shopping
after my lunch break" means: add whatever else fills the morning first, then shopping, so it
naturally lands in the first free gap after lunch. If the guidance can't be satisfied this
way (e.g. it names an event or constraint that doesn't actually exist on the calendar or in
the task list), say so plainly in your reply rather than silently ignoring it.

If a "Schedule window" line is included (e.g. planning just an evening rather than the whole
day), pass its two values to generate_schedule_blocks as start_time/end_time exactly as
given — they're already resolved, not something to reinterpret."""

# Per-mode tool sets for the tool model. day_planning is a separate, narrow
# flow (see DAY_PLANNING_ADDENDUM above), so offering the full tool list
# just gives a 1.2B model more ways to pick wrong. Names that don't exist in
# the live tool list are skipped; an empty result falls back to the full
# list (build_graph).
MODE_TOOL_NAMES = {
    "day_planning": ["add_planning_task", "generate_schedule_blocks", "get_todays_events", "get_calendar_events"],
}


# A lookup and a write in one batch run together, so the write can't use what
# the lookup found. The 1.2B tool model does this; the write waits a step.
LOOKUP_TOOLS = {"search_web", "search_news", "search_images", "search_videos", "fetch_url", "fetch_webpage"}
WRITE_AFTER_LOOKUP_TOOLS = writer.TEMPLATE_TOOLS | {"add_planning_task"}


def defer_writes_after_lookup(tool_calls: list[dict]) -> tuple[list[dict], list[dict]]:
    """(calls to run now, calls held back). Writes are held back only when the
    same batch also looks something up."""
    if not any(c.get("name") in LOOKUP_TOOLS for c in tool_calls):
        return list(tool_calls), []
    run = [c for c in tool_calls if c.get("name") not in WRITE_AFTER_LOOKUP_TOOLS]
    held = [c for c in tool_calls if c.get("name") in WRITE_AFTER_LOOKUP_TOOLS]
    return run, held


def _held_back_message(call: dict) -> ToolMessage:
    name = call.get("name")
    return ToolMessage(
        content=(
            f"Failed to run {name} yet: it was requested in the same step as a lookup, so it could not "
            f"use the lookup's results and was not run. Read the results above, then call {name} again "
            "with the details you found (or tell the user nothing useful was found)."
        ),
        tool_call_id=call["id"],
        name=name,
    )


_prompt_version = ""


def _record_prompt_version(tools: list) -> str:
    """Version id of everything the tool model can be shown (base prompt,
    mode addenda, tool schemas), with the git sha in front when the build
    provides one (GIT_SHA env). The full text is written once per version to
    <event log dir>/prompt_versions/<version>.json so a logged turn's exact
    prompt can be rebuilt after the code changes."""
    payload = {
        "system_prompt": SYSTEM_PROMPT,
        "addenda": {"one_shot": ONE_SHOT_ADDENDUM, "day_planning": DAY_PLANNING_ADDENDUM},
        "mode_tool_names": {k: sorted(v) for k, v in MODE_TOOL_NAMES.items()},
        "tools": [convert_to_openai_tool(t) for t in tools],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    sha = os.environ.get("GIT_SHA", "").strip()
    version = f"{sha[:10]}+{digest}" if sha else digest
    try:
        path = event_log.log_dir() / "prompt_versions" / f"{version}.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"prompt_version": version, "git_sha": sha or None, **payload}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except OSError as e:
        logger.warning("Could not write prompt version file: %s", e)
    return version


def get_prompt_version() -> str:
    """Identifies what the tool model was shown: a hash of the system prompt
    and the tool schemas, plus the git sha when the build provides one
    (GIT_SHA env). Set by build_graph."""
    return _prompt_version


def build_graph(checkpointer, mcp_tools: list | None = None):
    global _prompt_version
    tools = get_tools()
    if mcp_tools:
        local_names = {t.name for t in tools}
        for mcp_tool in mcp_tools:
            if mcp_tool.name in local_names:
                logger.warning(
                    "MCP tool '%s' has the same name as a local tool — the MCP "
                    "version will take precedence in the bound tool list.",
                    mcp_tool.name,
                )
        tools = tools + mcp_tools

    # Temperature 0.2, not the 0.7 other get_chat_llm() call sites use: this is
    # the only instance with bind_tools(), so the same call also picks the tool
    # and fills in its arguments (dates, search queries) alongside writing the
    # reply, and lower temperature favours consistent selection over warmth.
    # Building the client is pure object construction, so it is cached once.
    llm_with_tools = get_chat_llm(temperature=0.2).bind_tools(tools)
    _prompt_version = _record_prompt_version(tools)

    mode_tools = {}
    for mode_key, names in MODE_TOOL_NAMES.items():
        subset = [t for t in tools if t.name in names]
        if subset:
            mode_tools[mode_key] = subset
    llm_with_mode_tools = {
        mode_key: get_chat_llm(temperature=0.2).bind_tools(subset) for mode_key, subset in mode_tools.items()
    }

    # Tool list is fixed for the process lifetime, so this is computed once here
    # rather than every call_llm turn. ponytail: reuses the same chars/4 approximate
    # counter as trim_messages below (count_tokens_approximately) instead of a
    # second ad-hoc heuristic — precision doesn't matter, it's a reservation, not
    # an exact bill.
    global _tools_token_estimate
    _tools_token_estimate = count_tokens_approximately(
        [SystemMessage(content=json.dumps([convert_to_openai_tool(t) for t in tools]))]
    )

    # LM Studio's Unified KV Cache (on by default for concurrent
    # predictions) is a single pool shared across every in-flight request
    # to this model, not partitioned per caller — and LM Studio crashes
    # rather than queues when it's exhausted by simultaneous requests. This
    # app has no way to see what else is in flight on the LM Studio side,
    # so instead it guarantees there's never more than one: every call_llm
    # invocation, across every concurrent thread/turn/background job, waits
    # its turn here before actually hitting the chat model. Scoped to just
    # the completion call below — parallel tool execution isn't gated by
    # this, since tools don't touch the chat model's shared cache.
    llm_semaphore = asyncio.Semaphore(1)

    async def call_llm(state: MessagesState, config: RunnableConfig):
        last_user_msg = next(
            (m.content for m in reversed(state["messages"])
             if hasattr(m, "type") and m.type == "human"),
            ""
        )

        thread_id = (config or {}).get("configurable", {}).get("thread_id")
        one_shot = (config or {}).get("configurable", {}).get("one_shot", False)
        mode = (config or {}).get("configurable", {}).get("mode")

        addendum = ONE_SHOT_ADDENDUM if one_shot else ""
        if mode == "day_planning":
            addendum += DAY_PLANNING_ADDENDUM

        # Computed fresh every turn: the small tool model can't be trusted to
        # ask for the date, so the real value is always in the prompt (see
        # SYSTEM_PROMPT's "Date and Time Grounding" section).
        datetime_block = f"\n\nCURRENT DATE AND TIME: {format_now_human(settings.zoneinfo())}"

        system = SystemMessage(content=SYSTEM_PROMPT + addendum + datetime_block)
        # A fixed-id thread (e.g. "day_planning:<date>") reuses the same
        # thread_id across visits and is never swept, so unlike normal
        # threads its history can grow until it exceeds whatever context
        # length LM Studio's model was loaded with. Trim to a budget every
        # turn regardless of thread type, since this node is the one place
        # all of them route through. The
        # budget itself is LM Studio's live loaded_context_length when
        # LMSTUDIO_MANAGEMENT_URL is configured (utils/lmstudio_client.py),
        # else the dashboard-editable max_history_tokens fallback.
        #
        # That budget is the model's *total* context, not history's — the system
        # message and every bound tool schema are sent alongside history on every
        # call but never trimmed themselves, so their cost has to be reserved out
        # of the budget before history gets whatever's left. Without this, history
        # alone could grow to fill the full budget and the actual request (system +
        # tools + history) would still overflow the model's real context.
        tool_model_id = settings.lmstudio_chat_model
        budget = await get_history_budget_tokens(tool_model_id)
        reserved = count_tokens_approximately([system]) + _tools_token_estimate
        history_budget = max(budget - reserved, 0)
        if history_budget == 0:
            logger.warning(
                "System prompt + tools alone (~%d tok) meet or exceed the model's "
                "context budget (%d tok) — no room left for conversation history.",
                reserved, budget,
            )
        history = trim_messages(
            state["messages"],
            max_tokens=history_budget,
            token_counter="approximate",  # ponytail: chars/4 heuristic (langchain's count_tokens_approximately) — no real tokenizer available for whatever model LM Studio has loaded; swap in a real one if trimming precision ever matters
            strategy="last",
            start_on="human",
        )
        history = writer.tool_model_view(history)
        if not history:
            # A too-small history_budget (system+tools alone already at or
            # over the model's context) trims everything away, including
            # the current turn's own message — some chat templates (e.g.
            # Llama 3.1's official tool-calling template) then error
            # outright on having no user message at all, rather than a
            # clean "context length exceeded" response. Keep at least the
            # single most recent message so the request is well-formed;
            # worst case this slightly overflows the model's real context
            # and fails with a clearer error than a template crash.
            history = state["messages"][-1:]

        base_llm = llm_with_mode_tools[mode] if mode in llm_with_mode_tools else llm_with_tools
        # The model is dashboard-editable, so it can't be baked into the cached
        # client: .bind() layers this turn's model name over the client's default.
        active_llm = base_llm.bind(model=tool_model_id)
        async with llm_semaphore:
            response = await active_llm.ainvoke([system] + history)

        # Split-model handoff (agent/writer.py): only a final reply (no tool
        # calls) can be rewritten; a tool-calling response goes straight on.
        if not getattr(response, "tool_calls", None):
            draft = writer._text(response.content)
            new_text = await writer.finalize_reply(
                list(state["messages"]) + [response],
                draft=draft, thread_id=thread_id, mode=mode, one_shot=one_shot,
            )
            if new_text:
                response = AIMessage(
                    content=new_text,
                    id=response.id,
                    additional_kwargs={**(response.additional_kwargs or {}), writer.WRITER_FLAG: True},
                )
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    async def run_tools(state: MessagesState, config: RunnableConfig):
        cfg = (config or {}).get("configurable", {})
        thread_id = cfg.get("thread_id")
        messages = list(state["messages"])
        # A "tonight"/"tomorrow" request whose call carries some other date
        # (copied from recalled context) is corrected for this execution.
        user_text = writer.current_turn(messages).user_message
        fixed = fix_relative_dates(
            user_text, list(messages[-1].tool_calls or []), datetime.now(settings.zoneinfo())
        )
        if fixed:
            logger.info("Corrected tool-call date(s) to match %r", user_text)
            messages[-1] = messages[-1].model_copy(update={"tool_calls": fixed})
        cleaned = clean_search_queries(user_text, list(messages[-1].tool_calls or []))
        if cleaned:
            logger.info("Removed dates the user didn't give from search query: %s",
                        [c["args"].get("query") for c in cleaned if c["name"] in LOOKUP_TOOLS])
            messages[-1] = messages[-1].model_copy(update={"tool_calls": cleaned})
        run_now, held = defer_writes_after_lookup(list(messages[-1].tool_calls or []))
        if not held:
            return await tool_node.ainvoke({"messages": messages}, config)
        logger.info("Holding back %s until the lookup in the same step has returned", [c["name"] for c in held])
        messages[-1] = messages[-1].model_copy(update={"tool_calls": run_now})
        result = await tool_node.ainvoke({"messages": messages}, config)
        by_id = {m.tool_call_id: m for m in result["messages"]}
        by_id.update({c["id"]: _held_back_message(c) for c in held})
        order = [c["id"] for c in state["messages"][-1].tool_calls]
        return {"messages": [by_id[i] for i in order if i in by_id]}

    graph = StateGraph(MessagesState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", tools_condition)
    graph.add_edge("tools", "llm")

    return graph.compile(checkpointer=checkpointer)