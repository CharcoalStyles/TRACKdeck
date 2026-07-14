"""
Personal Assistant — FastAPI + LangGraph
----------------------------------------
Environment variables are loaded from .env at startup via python-dotenv.
Required vars: LM_STUDIO_URL, CHAT_MODEL, EMBEDDING_MODEL
"""
import os
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Load .env before anything that reads os.environ (i.e. before agent imports)
load_dotenv()

from agent.graph import build_graph
from agent.memory import MemoryStore, make_chroma_client, make_embedding_function
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from voice import router as voice_router

from routes.synth import router as synth_router

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

class AppState:
    graph = None
    memory: MemoryStore = None

app_state = AppState()

_thread_locks: dict[str, asyncio.Lock] = {}

def get_thread_lock(thread_id: str) -> asyncio.Lock:
    if thread_id not in _thread_locks:
        _thread_locks[thread_id] = asyncio.Lock()
    return _thread_locks[thread_id]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    chroma_client = make_chroma_client()
    embedding_fn = make_embedding_function()
    app_state.memory = MemoryStore(chroma_client, embedding_fn)

    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app_state.graph = build_graph(checkpointer, app_state.memory)
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(voice_router) # /voice
app.include_router(synth_router) # /synthesize


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TextRequest(BaseModel):
    text: str
    thread_id: str = "main"

class AssistantResponse(BaseModel):
    reply: str


# ---------------------------------------------------------------------------
# Shared agent runner
# ---------------------------------------------------------------------------

async def run_agent(text: str, thread_id: str = "main") -> str:
    if app_state.graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialised")

    config = {"configurable": {"thread_id": thread_id}}

    print("Agent initialised and ready to run")
    async with get_thread_lock(thread_id):
        print("Invoking agent...")
        result = await app_state.graph.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config=config,
        )

    for msg in result["messages"]:
    # Check if the LLM made a tool call
      if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tool_call in msg.tool_calls:
            print(f"🛠️ Tool Called: {tool_call['name']}")
            print(f"   Arguments:   {tool_call['args']}")
            
    # Optional: Check the corresponding tool response
      elif msg.type == "tool":
          print(f"🔄 Tool Output: {msg.content}\n")

    reply = next(
        (m.content for m in reversed(result["messages"]) if m.content),
        "Done.",
    )

    summary = f"User: {text}\nAssistant: {reply}"
    app_state.memory.save_conversation_summary(summary, thread_id=thread_id)

    return reply


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    static_file_path = os.path.join("static", "index.html")
    if os.path.exists(static_file_path):
        with open(static_file_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(content="<h1>static/index.html not found</h1>", status_code=404)

# 3. Mount the rest of the static folder for any assets/css/js if you add them later
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/text", response_model=AssistantResponse)
async def handle_text(request: TextRequest):
    print(request)
    reply = await run_agent(request.text, thread_id=request.thread_id)
    return AssistantResponse(reply=reply)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "graph_ready": app_state.graph is not None,
        "memory_ready": app_state.memory is not None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)