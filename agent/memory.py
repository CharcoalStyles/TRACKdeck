"""
agent/memory.py
---------------
Long-term semantic memory backed by Chroma (embedded mode).

Chroma runs inside the FastAPI process — no separate service needed.
Data is persisted to ./data/chroma_db/ on disk.

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

# ponytail: char-based estimate, not a real token count (tiktoken_enabled=False means
# we don't have the local embedder's actual tokenizer) — recalibrate if EMBEDDING_MODEL
# changes context length or tokenizer.
CHUNK_MAX_CHARS = 1000
CHUNK_OVERLAP_CHARS = 120


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap_chars: int = CHUNK_OVERLAP_CHARS) -> list[tuple[str, str]]:
    """
    Split text into chunks small enough for the embedder's context window.

    Returns (embed_text, stored_text) pairs: stored_text is the clean, non-overlapping
    slice (so joining every stored_text back together reproduces the original text
    exactly); embed_text has the previous chunk's tail prepended, so the *vector* still
    captures context across the boundary without duplicating stored text.
    """
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [(text, text)]

    stored: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            stored.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            for i in range(0, len(para), max_chars):
                stored.append(para[i : i + max_chars])
            current = ""
    if current:
        stored.append(current)
    if not stored:
        stored = [text]

    pairs = [(stored[0], stored[0])]
    for prev, cur in zip(stored, stored[1:]):
        tail = prev[-overlap_chars:]
        pairs.append((f"{tail}\n\n{cur}" if tail else cur, cur))
    return pairs


def _group_chunks(ids: list[str], documents: list[str], metadatas: list[dict], group_key: str) -> dict[str, dict]:
    """
    Group parallel (id, document, metadata) rows by metadata[group_key], sorted within
    each group by "chunk_index". Falls back to a row's own id as the group key when
    that metadata field is absent — pre-chunking legacy rows are each their own group
    of one, so old data keeps working with no migration step.

    Returns {group_key: {"metadata": first row's metadata, "text": joined stored_text}}.
    """
    groups: dict[str, list[tuple[int, str, dict]]] = {}
    for doc_id, doc, meta in zip(ids, documents, metadatas):
        key = meta.get(group_key) or doc_id
        groups.setdefault(key, []).append((meta.get("chunk_index", 0), doc, meta))

    result = {}
    for key, rows in groups.items():
        rows.sort(key=lambda r: r[0])
        result[key] = {
            "metadata": rows[0][2],
            "text": "\n\n".join(doc for _, doc, _ in rows),
        }
    return result


def make_embedding_function():
    """Returns a LangChain embedding wrapper pointed at LM Studio."""
    return OpenAIEmbeddings(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=os.environ["EMBEDDING_MODEL"],
        tiktoken_enabled=False,
        check_embedding_ctx_length=False,
    )


def make_chroma_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(
        path="./data/chroma_db",
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
        """Store a short summary of a completed conversation turn, chunked so no
        single embed call exceeds the embedder's context window."""
        # Clean the string and check if it's empty
        if not summary or not str(summary).strip():
            logger.warning("Attempted to save an empty summary for thread %s. Skipping embedding.", thread_id)
            return

        summary_id = f"{thread_id}_{int(time.time())}"
        logger.debug("Saving conversation summary %s: %s", summary_id, summary)

        pairs = chunk_text(summary)
        ids = [f"conv_{summary_id}::{i}" for i in range(len(pairs))]
        embeddings = [self._embed(embed_text) for embed_text, _ in pairs]
        documents = [stored_text for _, stored_text in pairs]
        metadatas = [
            {"thread_id": thread_id, "timestamp": int(time.time()), "summary_id": summary_id, "chunk_index": i}
            for i in range(len(pairs))
        ]
        self.conversations.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

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
        seen_summary_ids = set()
        for doc_id, doc, meta, distance in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            if exclude_thread_ids and meta.get("thread_id") in exclude_thread_ids:
                continue
            if max_distance is not None and distance > max_distance:
                continue
            summary_id = meta.get("summary_id") or doc_id
            if summary_id in seen_summary_ids:
                continue  # a later, worse-scoring chunk of a summary already matched
            seen_summary_ids.add(summary_id)
            matches.append({
                "document": doc,
                "thread_id": meta.get("thread_id"),
                "timestamp": meta.get("timestamp"),
                "distance": distance,
            })
            if len(matches) >= n_results:
                break
        return matches

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
        groups = _group_chunks(
            results.get("ids", []), results.get("documents", []), results.get("metadatas", []), "summary_id"
        )
        summaries = list(groups.values())
        if exclude_thread_ids:
            summaries = [s for s in summaries if s["metadata"].get("thread_id") not in exclude_thread_ids]
        summaries.sort(key=lambda s: s["metadata"].get("timestamp", 0))
        return [s["text"] for s in summaries]

    def get_conversation_by_thread(self, thread_id: str) -> Optional[str]:
        """Most recent conversation summary for one specific thread. Used
        by the daily digest to pull a check-in's reply out by its own
        dedicated thread (jobs/checkin.py mints one per check-in) rather
        than through the day-window fetch above."""
        if self.conversations.count() == 0:
            return None

        results = self.conversations.get(where={"thread_id": thread_id})
        groups = _group_chunks(
            results.get("ids", []), results.get("documents", []), results.get("metadatas", []), "summary_id"
        )
        if not groups:
            return None
        latest = max(groups.values(), key=lambda s: s["metadata"].get("timestamp", 0))
        return latest["text"]

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
        self.delete_note(note_id)  # clear any existing chunks before re-adding
        pairs = chunk_text(content)
        ids = [f"{note_id}::{i}" for i in range(len(pairs))]
        # Embed the title together with each chunk's body, not just the body — a
        # query that's really just the note's name (e.g. searching for a
        # note by something close to its title) should match reliably,
        # not only queries that happen to resemble the body's content.
        embeddings = [
            self._embed(f"{title}\n\n{embed_text}" if title else embed_text) for embed_text, _ in pairs
        ]
        documents = [stored_text for _, stored_text in pairs]
        metadatas = [
            {"note_id": note_id, "title": title, "path": path, "mtime": mtime, "project": project, "chunk_index": i}
            for i in range(len(pairs))
        ]
        self.notes.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def delete_note(self, note_id: str) -> None:
        try:
            results = self.notes.get(where={"note_id": note_id})
            ids = results.get("ids", [])
            if ids:
                self.notes.delete(ids=ids)
            else:
                self.notes.delete(ids=[note_id])  # legacy pre-chunking entry, no note_id metadata
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
        """note_id -> metadata for every indexed note (one entry per note, not
        per chunk). Used by reconciliation to find orphaned entries (file
        deleted) and stale ones (file changed since last indexed)."""
        if self.notes.count() == 0:
            return {}
        results = self.notes.get()
        groups = _group_chunks(
            results.get("ids", []), results.get("documents", []), results.get("metadatas", []), "note_id"
        )
        return {note_id: g["metadata"] for note_id, g in groups.items()}

    def search_notes(self, query: str, n_results: int = 5, project: str | None = None) -> list[dict]:
        """
        Semantic search over the notes index. Returns short excerpts, not
        full bodies — deliberately, to keep search results cheap on
        context. Callers should use read_note for the complete note.

        `project`, if given, scopes the search to that project's notes only
        (via a Chroma metadata `where` filter) instead of the whole vault.

        A note may be indexed as several chunks; over-fetches past n_results
        (same trick as search_conversations) so the results can be deduped
        back down to distinct notes, keeping each note's best-matching chunk.
        """
        if self.notes.count() == 0:
            return []
        embedding = self._embed(query)
        fetch_n = min(n_results * 4, self.notes.count())
        query_kwargs = {"query_embeddings": [embedding], "n_results": fetch_n}
        if project:
            query_kwargs["where"] = {"project": project}
        results = self.notes.query(**query_kwargs)
        output = []
        seen_note_ids = set()
        for chunk_id, doc, meta in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0]
        ):
            note_id = meta.get("note_id") or chunk_id
            if note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            excerpt = doc.strip().replace("\n", " ")
            if len(excerpt) > 400:
                excerpt = excerpt[:400].rsplit(" ", 1)[0] + "…"
            output.append({"id": note_id, "title": meta.get("title", "Untitled"), "excerpt": excerpt})
            if len(output) >= n_results:
                break
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