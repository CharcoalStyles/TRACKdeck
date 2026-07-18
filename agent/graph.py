"""
agent/graph.py
--------------
Builds and returns the compiled LangGraph agent.
LLM connection is configured via environment variables.
"""

import os

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from agent.memory import MemoryStore
from agent.tools.all_tools import get_tools


SYSTEM_PROMPT = """You are a personal assistant agent with access to tools including get_current_datetime and 
web_search.

## MANDATORY: Date and Time Grounding
You do NOT know the current date or time. Your training data has a cutoff and you have 
no built-in clock. Any date/time knowledge you seem to have is unreliable and likely wrong.

Before performing ANY action that involves a relative time reference (today, tomorrow, 
next week, in an hour, this weekend, etc.), you MUST:
1. Call get_current_datetime first, before anything else.
2. Compute the actual target date/time from that result.
3. Only then proceed with the action.

Do not skip this step even if you did it earlier in the conversation — always re-check 
for date/time-sensitive requests, since time may have passed.

Never guess, estimate, or use a remembered date. If you catch yourself about to write a 
year or date without having called get_current_datetime in this turn, stop and call it.

## MANDATORY: Resolving Ambiguous or Unverified Details
You do NOT have live knowledge of real-world businesses, addresses, current events, prices, 
or other real-world specifics. If a request requires you to supply a real-world detail you 
are not certain of — a business name, address, phone number, opening hours, current price, 
etc. — you MUST call web_search to find it rather than inventing or inferring one from 
memory.

This applies even if the request seems minor or the user seems to expect you to "just 
know." Examples that require a search:
- "add the details of [a business] in [location]" → search for the actual business
- "find a good [X] near [Y]" → search, don't guess
- "what's the address of..." → search, don't guess

If a search returns nothing usable, tell the user you couldn't verify the detail rather 
than fabricating one.

## General Rule
When in doubt about whether a fact is current, real, or time-sensitive, treat it as 
unknown and use a tool to verify it. Never present a guessed or fabricated fact as if it 
were verified."""

ONE_SHOT_ADDENDUM = """

## MANDATORY: One-Shot Mode
This request is arriving through a device with no way to hear a follow-up question and no 
way to continue the conversation — this is your only chance to respond. You MUST NOT end 
your final reply with a clarifying question, and you MUST NOT leave the task incomplete 
waiting for more information.

Instead:
1. Make the most reasonable assumption for anything ambiguous or unspecified (e.g. an 
   unspecified time defaults to a sensible near-future slot; an unspecified duration 
   defaults to something typical for that kind of event).
2. Complete the requested action fully using that assumption.
3. In your final reply, briefly state what you assumed, so it can be corrected next time 
   if it's wrong — but always still complete the action rather than only asking about it.

Only decline to guess if a piece of information is truly required and no reasonable 
default exists (e.g. you cannot invent a business name that doesn't exist). In that case, 
say clearly what's missing and what you did anyway with the rest of the request, rather 
than leaving everything undone."""

def build_graph(checkpointer, memory: MemoryStore):
    llm = ChatOpenAI(
        base_url=os.environ["LM_STUDIO_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=0.7,
    )

    tools = get_tools(memory)
    llm_with_tools = llm.bind_tools(tools)

    def call_llm(state: MessagesState, config: RunnableConfig):
        last_user_msg = next(
            (m.content for m in reversed(state["messages"])
             if hasattr(m, "type") and m.type == "human"),
            ""
        )

        recalled = memory.search_conversations(last_user_msg, n_results=3)
        memory_block = ""
        if recalled:
            memory_block = "\n\nRELEVANT PAST CONTEXT:\n" + "\n---\n".join(recalled)

        one_shot = (config or {}).get("configurable", {}).get("one_shot", False)
        addendum = ONE_SHOT_ADDENDUM if one_shot else ""

        system = SystemMessage(content=SYSTEM_PROMPT + addendum + memory_block)
        response = llm_with_tools.invoke([system] + state["messages"])
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    graph = StateGraph(MessagesState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", tools_condition)
    graph.add_edge("tools", "llm")

    return graph.compile(checkpointer=checkpointer)