"""
agent/graph.py
--------------
Builds and returns the compiled LangGraph agent.
LLM connection is configured via environment variables.
"""

import asyncio
import json
import logging
import time

from langchain_core.messages import SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from agent.memory import MemoryStore
from agent.settings import settings
from agent.tools.all_tools import get_tools
from utils import vault
from utils.llm_client import get_chat_llm
from utils.lmstudio_client import get_history_budget_tokens
from utils.openrouter_client import get_history_budget_tokens as get_openrouter_history_budget_tokens
from utils.recall_log_store import log_recall

logger = logging.getLogger(__name__)

# ponytail: static guess at Gemini's usable context — Google doesn't expose a
# live "loaded context length" like LM Studio's management API does, and
# building a second discovery mechanism for one hosted model isn't worth it.
# Bump this if a different Gemini model/context tier is tried. OpenRouter
# doesn't need an equivalent constant: its model catalog is public and
# already fetched for the dashboard's OpenRouter Models admin page
# (utils/openrouter_client.py), so its history budget is looked up live
# from that same catalog instead of guessed.
GEMINI_HISTORY_BUDGET_TOKENS = 200_000

# Fixed-thread-id prefix for per-project chats (agent/runtime.py's run_agent
# skips normal keyword/recency resolution whenever an explicit thread_id is
# passed, so "project_<slug>" threads are automatically un-addressable by
# voice keyword and never swept by jobs/digest.py — same trick as the
# "onboarding"/"profile_chat" fixed threads below).
PROJECT_THREAD_PREFIX = "project_"


SYSTEM_PROMPT = """You are a personal assistant agent with access to tools including get_current_datetime and
search_web.

## MANDATORY: Date and Time Grounding
You do NOT know the current date or time — your training data has a cutoff and you have no
built-in clock, so any date/time knowledge you seem to have is unreliable. Before any action
involving a relative time reference (today, tomorrow, next week, in an hour, this weekend,
etc.), call get_current_datetime first and compute the actual target date/time from that
result — every time, even if you already called it earlier this conversation, since time may
have passed. Never guess, estimate, or reuse a remembered date.

If the user gives a bare 12-hour time with no AM/PM (e.g. "9 o'clock", "at 9"), default to AM
unless context implies otherwise ("9 o'clock tonight" → PM; "lunch at 12" → PM). State the
assumption in your reply so it can be corrected if wrong.

## MANDATORY: Verifying Real-World and Time-Sensitive Facts
You do NOT have live knowledge of real-world businesses, addresses, current events, prices, or
other real-world specifics — call search_web rather than inventing or inferring one from
memory, even if the request seems minor or expects you to "just know" (e.g. "add [a
business]'s details", "find a good [X] near [Y]", "what's the address of..."). If a search
returns nothing usable, say you couldn't verify it rather than fabricating one.

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

## MANDATORY: Tool Errors
If a tool call's result indicates an error, you MUST NOT report the action as successful.
Either fix the call and retry once with corrected arguments, or tell the user plainly that it
failed — never describe a failed tool call as if it worked.

## Activity Logging
If the user describes something they just did or are currently doing that fits a Meal,
Exercise, Project Work, Socializing, or Rest activity, use log_activity to record it — but
only when they're actually narrating an activity occurrence, not for hypotheticals, plans,
or unrelated chat. Do this quietly alongside your normal reply; don't interrogate them for
every field first.

## Projects
If the user is developing an ongoing project — ideas, notes, or plans that build up over
many separate conversations, not a single one-off note and not a specific person/topic —
check list_projects (or just try get_or_create_project) to get or create a dedicated vault
folder for it. Use save_note — still with a title and content like any other note, plus
that project's name — to file its notes together there, and pass the same project name to
search_notes whenever the user is actively discussing that project, so retrieval stays
scoped to it instead of pulling in unrelated notes.

## Tone
A little warmth is fine, but keep it in check — especially on heavier or personal
topics (self-criticism, mental health, executive function, motivation struggles,
etc.). Skip reflexive validation and therapy-speak ("that takes incredible
honesty", "what a profound insight") — respond to what the user actually said
instead of praising them for saying it. Emoji should be rare, not a default.
Routine, lighter requests can still get a normal friendly tone."""

LEARNING_ADDENDUM = """

## Learning About the User
Notice durable facts worth remembering as they come up naturally — preferences, recurring
people/places, ongoing projects, routines, things they care about — and record them with
remember_about_me directly (it always resolves the right note itself; never search for it or
track an id). For a specific person/project/sub-topic, use get_or_create_linked_note instead.
Never use remember_about_me mode="replace" on a section holding multiple entries (e.g.
"People") — it wipes everything in it, not just one.

Be selective, not exhaustive — most requests have nothing worth recording (a one-off task like
"turn off the kitchen light" has nothing to learn from), and this should never delay or
distract from completing what was actually asked. It's a secondary, occasional side effect."""

# Fixed per-turn overhead that call_llm's history budget must reserve room for —
# see get_fixed_overhead_tokens below. Base prompt cost is static (computed once at
# import time); the tools estimate is set by build_graph once the tool list is known.
_BASE_SYSTEM_PROMPT_TOKENS = count_tokens_approximately([SystemMessage(content=SYSTEM_PROMPT)])
_tools_token_estimate: int = 0


def get_fixed_overhead_tokens() -> int:
    """Base system prompt + bound tool schemas, no mode addendum/memory block
    (those vary per turn and aren't known outside call_llm) — a lower-bound
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

ONBOARDING_ADDENDUM = """

## Mode: Guided Onboarding
You're actively interviewing the user to build out their About Me profile — driving the
conversation, not waiting for facts to come up naturally (unlike passive learning mode).

They already filled out a basics form before this conversation started (name, birthday,
location, occupation, job, people, and short notes on preferences/routine/interests/health &
goals/important dates may already be recorded) — call read_about_me first to see what's there,
and don't re-ask anything it already answered. Location is set separately via
set_home_location; only touch that if they bring up moving. Go deeper on whatever they gave
short answers to, and offer to say more about specific people if several were listed.

Use as a guide for what's still thin, not a script to read verbatim:
  - Preferences, People, Routine, Interests — go deeper than the form's short notes
  - Values (guiding principles — often deliberately worked out, sometimes already ranked;
    don't push if unarticulated. If the form gave a full ranked list, use remember_about_me
    with mode="replace" so a later correction replaces it rather than appending a
    conflicting one)
  - Health & Goals, Important Dates — whatever's already there

Follow their actual answers rather than marching down this list — dig into what's worth
digging into, follow topics not on the list if they seem worth capturing, and ask one thing
at a time.

## MANDATORY: Recording as you go
For every response: decide if anything's worth recording, and if so record it immediately —
before asking anything else. Never batch facts for the end; the user can stop at any point
and whatever's unsaved is lost. Briefly acknowledge what you recorded ("Got it" is enough)
and continue.

For a specific person (e.g. going through several one by one) or any other distinct
sub-topic likely to accumulate detail later, use get_or_create_linked_note instead of
writing into a shared About Me section.

Once the main areas feel reasonably covered, call mark_onboarding_complete, let them know,
and mention they can add more later via the dashboard — don't keep interviewing
indefinitely."""

PROFILE_CHAT_ADDENDUM = """

## Mode: Profile Query & Update
This conversation is specifically about the user's own profile — answering what's currently
recorded in About Me, and letting them correct or add to it. Use read_about_me before
answering what's known, and remember_about_me to record corrections/additions given
directly.

For a correction about a specific person/project/sub-topic, use get_or_create_linked_note
and edit that note directly rather than the shared About Me section — editing a section
holding multiple entries (e.g. "People") risks losing every other entry in it, not just the
one fixed."""

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

PROJECT_CHAT_ADDENDUM = """

## Mode: Project Chat — {project}
Focused specifically on the "{project}" project. A PROJECT NOTES block below lists every
note in its folder — your primary source; use read_note (with the id shown) for full
content when an excerpt isn't enough, and search_notes/save_note with project="{project}"
for deeper search or new notes (still needs its own title/content — project just scopes
where it's filed).

Stay scoped to this project — say so rather than answering from general knowledge if the
user asks about something unrelated."""

PROJECT_AGENT_ADDENDUM = """

## Mode: Project Agent — {project}
The message below is a goal to complete autonomously for "{project}" in this turn, with no
back-and-forth — don't ask a clarifying question or just describe what you'd do; actually do
the work with your tools and produce the real result.

A PROJECT NOTES block below lists every note in this project's folder — check it first to
build on what's there. Use search_notes/read_note (project="{project}") for anything the
excerpts don't cover, search_web/fetch_webpage for anything not already in the vault.

When the goal calls for documentation, write it: save_note with a real title/content and
project="{project}". Summarizing what a note *would* say hasn't completed the goal — it has
to actually exist.

Stay scoped to "{project}" — if part of the goal needs something outside it, say so and do
the rest anyway rather than leaving it all undone.

This is your only turn for this goal — work through every part before ending, don't stop
partway. Once done, reply with a short summary of what you did and where to find it (e.g.
note title(s)), not the full content again."""

def build_graph(checkpointer, memory: MemoryStore, mcp_tools: list | None = None):
    tools = get_tools(memory)
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

    # settings.llm_provider (agent/settings.py) is live-switchable from the
    # dashboard's Settings page, no restart — so unlike before, the
    # tool-bound LLM can't be built once here for a single fixed provider.
    # Each provider actually used gets its own cached client instead (0.2,
    # not the 0.7 default other get_chat_llm() call sites use — this is the
    # only instance with bind_tools() below, so the same call also decides
    # which tool to call and fills in its arguments (dates, search queries,
    # note content) alongside writing the final reply; lower temperature
    # trades a little conversational warmth for more consistent tool
    # selection/argument fidelity, which matters more here). Building a
    # ChatOpenAI/ChatGoogleGenerativeAI client is pure object construction
    # (no network call), so caching is just to avoid redoing it every turn,
    # not a correctness requirement — call_llm below picks the cache entry
    # for whichever provider settings.llm_provider currently names.
    llm_with_tools_by_provider = {}

    def get_llm_with_tools(provider: str):
        if provider not in llm_with_tools_by_provider:
            llm_with_tools_by_provider[provider] = get_chat_llm(temperature=0.2, provider=provider).bind_tools(
                tools
            )
        return llm_with_tools_by_provider[provider]

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
    # the completion call below — recall/embedding lookups and parallel
    # tool execution aren't gated by this, since those don't touch the
    # chat model's shared cache.
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
        agent_run = (config or {}).get("configurable", {}).get("agent_run", False)

        # Project name isn't a separate request field — it's derived from the
        # thread id itself, same "always resolves the same way" pattern as
        # every other fixed-path lookup in this codebase (About Me, linked
        # notes). See PROJECT_THREAD_PREFIX above.
        project_slug = None
        if mode == "project_chat" and thread_id and thread_id.startswith(PROJECT_THREAD_PREFIX):
            project_slug = thread_id[len(PROJECT_THREAD_PREFIX):]

        memory_block = ""
        if project_slug:
            # Deterministic, code-filtered retrieval instead of cross-thread
            # semantic recall — a different project's chat leaking in here
            # would defeat the point of a project-scoped chat, and this is
            # the actual scoping guarantee, not just a prompt instruction.
            project_notes = await asyncio.to_thread(vault.list_notes_summary)
            project_notes = [n for n in project_notes if n["project"] == project_slug]
            if project_notes:
                memory_block = "\n\nPROJECT NOTES:\n" + "\n".join(
                    f"[id: {n['id']}] {n['title']} — {n['excerpt']}" for n in project_notes
                )
        else:
            # Never recall from onboarding/profile_chat (dense, deliberately
            # elicited personal/health disclosures — the root cause of the
            # cross-thread leak this filtering fixes) or from the thread
            # currently running (its own history is already in state["messages"],
            # so recalling it here would just be a redundant duplicate).
            exclude_thread_ids = {t for t in (thread_id, "onboarding", "profile_chat") if t}
            min_timestamp = int(time.time()) - settings.recall_recency_days * 86400

            # MemoryStore/Chroma has no async client, so this still blocks — but
            # to_thread keeps it off the event loop instead of freezing every
            # other concurrent request for the duration of the search.
            recalled = await asyncio.to_thread(
                memory.search_conversations,
                last_user_msg,
                n_results=3,
                exclude_thread_ids=exclude_thread_ids,
                max_distance=settings.recall_max_distance,
                min_timestamp=min_timestamp,
            )
            if recalled:
                memory_block = "\n\nRELEVANT PAST CONTEXT:\n" + "\n---\n".join(
                    r["document"] for r in recalled
                )
            if thread_id:
                await asyncio.to_thread(log_recall, thread_id, last_user_msg, recalled)

        addendum = ONE_SHOT_ADDENDUM if one_shot else ""
        if mode == "onboarding":
            addendum += ONBOARDING_ADDENDUM
        elif mode == "profile_chat":
            addendum += PROFILE_CHAT_ADDENDUM
        elif mode == "day_planning":
            addendum += DAY_PLANNING_ADDENDUM
        elif project_slug and agent_run:
            addendum += PROJECT_AGENT_ADDENDUM.format(project=project_slug)
        elif project_slug:
            addendum += PROJECT_CHAT_ADDENDUM.format(project=project_slug)
        elif settings.learning_mode:
            addendum += LEARNING_ADDENDUM

        # Read once per turn — live-switchable via the dashboard's Settings
        # page (agent/settings.py's llm_provider), so every branch below
        # keys off this local rather than a value frozen at graph-build time.
        provider = settings.llm_provider

        system = SystemMessage(content=SYSTEM_PROMPT + addendum + memory_block)
        # "onboarding"/"profile_chat"/"project_<slug>" threads reuse the same
        # thread_id forever and are never swept (see PROJECT_THREAD_PREFIX
        # comment above), so unlike normal threads their history can grow
        # until it exceeds whatever context length LM Studio's model was
        # loaded with. Trim to a budget every turn regardless of thread type,
        # since this node is the one place all of them route through. The
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
        if provider == "lmstudio":
            budget = await get_history_budget_tokens()
        elif provider == "openrouter":
            budget = await get_openrouter_history_budget_tokens()
        else:
            budget = GEMINI_HISTORY_BUDGET_TOKENS
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
        llm_with_tools = get_llm_with_tools(provider)
        # Both lmstudio and openrouter have a dashboard-editable model
        # (settings.lmstudio_chat_model / settings.openrouter_chat_model, see
        # their respective Models admin pages), so neither can be baked into
        # llm_with_tools at cache-build time. .bind() layers the current
        # model name into this call's request payload without rebuilding the
        # tool-bound client — langchain_openai merges bound kwargs over the
        # client's own default_params, so this wins over whatever model
        # get_chat_llm() constructed the client with when it was cached.
        # gemini has no such live switch, so it skips straight to the plain
        # ainvoke below.
        if provider == "lmstudio":
            active_llm = llm_with_tools.bind(model=settings.lmstudio_chat_model)
            async with llm_semaphore:
                response = await active_llm.ainvoke([system] + history)
        elif provider == "openrouter":
            # No concurrency gate here — cloud API, not LM Studio's shared
            # unified KV cache that llm_semaphore above protects.
            active_llm = llm_with_tools.bind(model=settings.openrouter_chat_model)
            response = await active_llm.ainvoke([system] + history)
        else:
            # No concurrency gate — llm_semaphore above exists only to protect
            # LM Studio's shared unified KV cache; a cloud API has no such
            # constraint.
            response = await llm_with_tools.ainvoke([system] + history)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    graph = StateGraph(MessagesState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", tools_condition)
    graph.add_edge("tools", "llm")

    return graph.compile(checkpointer=checkpointer)