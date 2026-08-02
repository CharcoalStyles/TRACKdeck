"""
agent/memory.py
---------------
Long-term semantic memory backed by Chroma (embedded mode).

Chroma runs inside the FastAPI process — no separate service needed.
Data is persisted to ./chroma_db/ on disk.

Two collections:
  - "conversations"  : summaries of past exchanges, for contextual recall
  - "notes"          : user-saved notes, searchable by content

Embeddings are generated locally via LM Studio's /v1/embeddings endpoint.
The embedding model is configured via the EMBEDDING_MODEL env var.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import chromadb
from chromadb import Settings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


def make_embedding_function():
    """Returns a LangChain embedding wrapper pointed at LM Studio."""
    return OpenAIEmbeddings(
        base_url=os.environ["LM_STUDIO_URL"],
        api_key="lm-studio",
        model=os.environ["EMBEDDING_MODEL"],
        tiktoken_enabled=False,
        check_embedding_ctx_length=False,
    )


def make_chroma_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(
        path="./chroma_db",
        settings=Settings(anonymized_telemetry=False),
    )


class MemoryStore:
    """
    Thin wrapper around two Chroma collections.
    Initialise once at startup, pass via app.state.
    """

    def __init__(self, client: chromadb.ClientAPI, embedding_fn):
        self._ef = embedding_fn
        self._client = client

        self.conversations = client.get_or_create_collection(
            name="conversations",
            metadata={"hnsw:space": "cosine"},
        )
        self.notes = client.get_or_create_collection(
            name="notes",
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def save_conversation_summary(self, summary: str, thread_id: str = "main") -> None:
        """Store a short summary of a completed conversation turn."""
        # Clean the string and check if it's empty
        if not summary or not str(summary).strip():
            logger.warning("Attempted to save an empty summary for thread %s. Skipping embedding.", thread_id)
            return

        doc_id = f"conv_{thread_id}_{int(time.time())}"
        logger.debug("Saving conversation summary %s: %s", doc_id, summary)

        embedding = self._embed(summary)
        self.conversations.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[summary],
            metadatas=[{"thread_id": thread_id, "timestamp": int(time.time())}],
        )

    def search_conversations(
        self,
        query: str,
        n_results: int = 3,
        exclude_thread_ids: set[str] | None = None,
        max_distance: float | None = None,
        min_timestamp: int | None = None,
    ) -> list[dict]:
        """
        Find past conversation summaries relevant to the current query.

        exclude_thread_ids/max_distance/min_timestamp exist because a plain
        similarity query has no idea which thread it's being asked from or
        how relevant/recent a "nearest" match actually is — see
        agent/graph.py's call_llm, the only caller, for how these get set.
        Over-fetches past n_results since exclusion/distance filtering
        happens after the query, then trims back down.

        Returns [{"document", "thread_id", "timestamp", "distance"}, ...],
        richer than a plain list of strings so callers can log exactly what
        was recalled, not just the text that got injected.
        """
        if self.conversations.count() == 0:
            return []
        embedding = self._embed(query)
        fetch_n = min(n_results * 4, self.conversations.count())
        query_kwargs = {"query_embeddings": [embedding], "n_results": fetch_n}
        if min_timestamp is not None:
            query_kwargs["where"] = {"timestamp": {"$gte": min_timestamp}}
        results = self.conversations.query(**query_kwargs)
        if not results["documents"]:
            return []

        matches = []
        for doc, meta, distance in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            if exclude_thread_ids and meta.get("thread_id") in exclude_thread_ids:
                continue
            if max_distance is not None and distance > max_distance:
                continue
            matches.append({
                "document": doc,
                "thread_id": meta.get("thread_id"),
                "timestamp": meta.get("timestamp"),
                "distance": distance,
            })
        return matches[:n_results]

    def get_conversations_between(
        self, start_ts: int, end_ts: int, exclude_thread_ids: set[str] | None = None
    ) -> list[str]:
        """
        Return raw conversation summaries recorded within [start_ts, end_ts]
        (UTC epoch seconds, inclusive), oldest first. Used by the daily
        digest job — a direct metadata-filtered fetch, not a similarity
        search.

        exclude_thread_ids lets a caller pull certain threads out of the
        generic log — the digest uses this to keep mental-health check-in
        replies (jobs/checkin.py) out of the freeform "today's activity"
        block since it surfaces those separately via
        get_conversation_by_thread.
        """
        if self.conversations.count() == 0:
            return []

        results = self.conversations.get(
            where={
                "$and": [
                    {"timestamp": {"$gte": start_ts}},
                    {"timestamp": {"$lte": end_ts}},
                ]
            },
        )
        pairs = list(zip(results.get("documents", []), results.get("metadatas", [])))
        if exclude_thread_ids:
            pairs = [p for p in pairs if p[1].get("thread_id") not in exclude_thread_ids]
        pairs.sort(key=lambda p: p[1].get("timestamp", 0))
        return [doc for doc, _ in pairs]

    def get_conversation_by_thread(self, thread_id: str) -> Optional[str]:
        """Most recent conversation summary for one specific thread. Used
        by the daily digest to pull a check-in's reply out by its own
        dedicated thread (jobs/checkin.py mints one per check-in) rather
        than through the day-window fetch above."""
        if self.conversations.count() == 0:
            return None

        results = self.conversations.get(where={"thread_id": thread_id})
        pairs = list(zip(results.get("documents", []), results.get("metadatas", [])))
        if not pairs:
            return None
        pairs.sort(key=lambda p: p[1].get("timestamp", 0))
        return pairs[-1][0]

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def upsert_note(
        self, note_id: str, content: str, title: str, path: str, mtime: float, project: str = ""
    ) -> None:
        """
        Index (or re-index) a note file by its stable frontmatter id. The
        markdown file on disk is the source of truth — this just keeps the
        search index current with it. Safe to call repeatedly for the same
        note; always overwrites rather than duplicating.

        `project` is the note's containing project folder name, or "" for a
        vault-root note — Chroma metadata values can't be None, so an empty
        string is the "no project" sentinel. Lets search_notes scope a query
        to one project via a `where` filter.
        """
        if not content or not str(content).strip():
            content = title or "Untitled"
        # Embed the title together with the body, not just the body — a
        # query that's really just the note's name (e.g. searching for a
        # note by something close to its title) should match reliably,
        # not only queries that happen to resemble the body's content.
        embedding_text = f"{title}\n\n{content}" if title else content
        embedding = self._embed(embedding_text)
        self.notes.upsert(
            ids=[note_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"title": title, "path": path, "mtime": mtime, "project": project}],
        )

    def delete_note(self, note_id: str) -> None:
        try:
            self.notes.delete(ids=[note_id])
        except Exception:
            pass  # already gone / never indexed — fine either way

    def delete_note_by_path(self, path: str) -> None:
        """Used by the live watcher on delete events, where we don't have
        the file (and therefore its id) available anymore."""
        results = self.notes.get(where={"path": path})
        ids = results.get("ids", [])
        if ids:
            self.notes.delete(ids=ids)

    def list_indexed_notes(self) -> dict:
        """id -> metadata for every indexed note. Used by reconciliation to
        find orphaned entries (file deleted) and stale ones (file changed
        since last indexed)."""
        if self.notes.count() == 0:
            return {}
        results = self.notes.get()
        return {
            note_id: meta
            for note_id, meta in zip(results.get("ids", []), results.get("metadatas", []))
        }

    def search_notes(self, query: str, n_results: int = 5, project: str | None = None) -> list[dict]:
        """
        Semantic search over the notes index. Returns short excerpts, not
        full bodies — deliberately, to keep search results cheap on
        context. Callers should use read_note for the complete note.

        `project`, if given, scopes the search to that project's notes only
        (via a Chroma metadata `where` filter) instead of the whole vault.
        """
        if self.notes.count() == 0:
            return []
        embedding = self._embed(query)
        query_kwargs = {
            "query_embeddings": [embedding],
            "n_results": min(n_results, self.notes.count()),
        }
        if project:
            query_kwargs["where"] = {"project": project}
        results = self.notes.query(**query_kwargs)
        output = []
        for note_id, doc, meta in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0]
        ):
            excerpt = doc.strip().replace("\n", " ")
            if len(excerpt) > 400:
                excerpt = excerpt[:400].rsplit(" ", 1)[0] + "…"
            output.append({"id": note_id, "title": meta.get("title", "Untitled"), "excerpt": excerpt})
        return output

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
      # Force convert to a completely clean, raw python string
      clean_text = str(text)

      # Fallback guard if the string turns out empty
      if not clean_text.strip():
          clean_text = "Empty summary"

      return self._ef.embed_query(clean_text)