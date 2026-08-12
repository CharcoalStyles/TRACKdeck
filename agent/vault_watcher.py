"""
agent/vault_watcher.py
-----------------------
Keeps the Chroma notes index in sync with the on-disk vault, and
auto-processes anything dropped in Inbox/ into a real, indexed note.

Two mechanisms, working together:

  - watch_vault(): a live watchfiles-based watcher for near-real-time
    updates while the app is running.
  - reconcile_vault(): a full sweep (run once at startup, and callable on
    demand) that catches anything the live watcher missed — a change that
    landed while the app was down, a dropped filesystem event, a failed
    embedding call. This is the actual correctness guarantee; the live
    watcher is a freshness optimization layered on top of it, not the
    thing you should have to trust to be perfect.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from langchain_openai import ChatOpenAI
from watchfiles import Change, awatch

from agent.memory import MemoryStore
from utils import vault
from utils.notify import notify_error, send_gotify

logger = logging.getLogger(__name__)

INGEST_PROMPT = """You are filing a raw note into a personal knowledge vault. Read the \
content below and respond with ONLY a JSON object (no other text, no markdown fences) \
with this exact shape:

{{"title": "A short, specific title", "tags": ["lowercase", "tag", "words"]}}

Pick 1-5 tags that categorize the content. The title should be concise and specific enough \
to tell this note apart from others like it.

Content:
{content}
"""


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def _index_note_sync(memory: MemoryStore, note: vault.Note) -> None:
    project = "" if note.path.parent == vault.vault_root() else note.path.parent.name
    memory.upsert_note(
        note_id=note.id,
        content=note.body,
        title=note.title,
        path=str(note.path.relative_to(vault.vault_root())),
        mtime=note.path.stat().st_mtime,
        project=project,
    )


async def index_note_file(memory: MemoryStore, path: Path) -> None:
    """(Re)index a single vault-root note file. Safe to call repeatedly.
    Silently does nothing if the file isn't a valid managed note."""
    note = vault.parse_note(path)
    if note is None:
        return
    await asyncio.to_thread(_index_note_sync, memory, note)


# ---------------------------------------------------------------------------
# Inbox ingestion
# ---------------------------------------------------------------------------

def _generate_inbox_frontmatter(content: str) -> dict:
    """Blocking LLM call — run via asyncio.to_thread from async code."""
    llm = ChatOpenAI(
        base_url=os.environ["LMSTUDIO_OPENAI_URL"],
        api_key="lm-studio",
        model=os.environ["CHAT_MODEL"],
        temperature=0.3,
    )
    response = llm.invoke(INGEST_PROMPT.format(content=content))
    raw = response.content.strip()
    # be forgiving of stray markdown fences some local models add anyway
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    return {
        "title": (data.get("title") or "Untitled").strip(),
        "tags": [t.strip().lower() for t in (data.get("tags") or []) if str(t).strip()],
    }


# Startup reconcile_vault() and the live watch_vault() run as independent
# concurrent tasks (see main.py's lifespan) and can both observe the same
# freshly-dropped Inbox file. This in-process claim set makes the
# check-and-claim atomic (no await between membership check and insert, so
# nothing can interleave under asyncio's cooperative scheduling) so only one
# of them actually processes a given file.
_processing_inbox_files: set[Path] = set()


async def process_inbox_file(memory: MemoryStore, path: Path) -> None:
    """
    Turn a raw file in Inbox/ into a proper managed note at the vault
    root, index it, and remove the Inbox copy. Any failure here is
    reported via Gotify rather than raised — this runs unattended, with
    no one watching an HTTP response.
    """
    key = path.resolve()
    if key in _processing_inbox_files:
        return  # already being handled by a concurrent call (reconcile vs watcher)
    _processing_inbox_files.add(key)

    try:
        if not path.exists():
            return  # already handled, or removed before we got to it

        raw_text = await asyncio.to_thread(path.read_text, "utf-8")
        raw_text = raw_text.strip()
        if not raw_text:
            return

        # If this already has valid frontmatter, it's not a raw inbox drop
        # (e.g. a processed note that got synced back into Inbox by
        # accident) — leave it alone rather than re-ingesting it.
        if raw_text.startswith(vault.FRONTMATTER_DELIM):
            if vault.parse_note(path) is not None:
                return

        fm = await asyncio.to_thread(_generate_inbox_frontmatter, raw_text)

        now = vault.now_iso()
        note = vault.Note(
            id=vault.generate_id(),
            title=fm["title"],
            created=now,
            updated=now,
            tags=fm["tags"],
            aliases=[],
            source="inbox",
            body=raw_text,
        )
        dest_path = vault.unique_note_path(note.title)
        note.path = dest_path

        content = vault.serialize_note(note)
        await asyncio.to_thread(vault.write_note_atomic, dest_path, content)
        await index_note_file(memory, dest_path)
        await asyncio.to_thread(path.unlink, missing_ok=True)

        await asyncio.to_thread(
            send_gotify,
            "Note ingested",
            f'"{note.title}" — tags: {", ".join(note.tags) or "none"}',
            3,
        )

    except Exception as e:
        logger.error("Failed to process inbox file %s: %s", path, e)
        await asyncio.to_thread(notify_error, f"Inbox processing failed for {path.name}", e)
    finally:
        _processing_inbox_files.discard(key)


# ---------------------------------------------------------------------------
# Sync-conflict alerts
# ---------------------------------------------------------------------------
#
# is_ignorable() correctly keeps *.sync-conflict-* files out of the note
# index (they're Syncthing's doing, not a real note) — but silently
# ignoring them entirely means a genuine multi-device edit conflict could
# sit in the vault unnoticed indefinitely. This surfaces it via Gotify
# instead, without changing how they're indexed.

# In-process dedup so a conflict file already alerted on doesn't re-alert
# every reconciliation sweep (or every debounced watcher event) for as
# long as it sits there unresolved. Resets on restart — an occasional
# duplicate alert after a restart is a fine tradeoff for not persisting
# this anywhere.
_alerted_conflict_paths: set[Path] = set()


def _find_conflict_files() -> list[Path]:
    root = vault.vault_root()
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file() and "sync-conflict" in p.name]


async def _alert_new_conflict_files(paths) -> None:
    new_paths = [p for p in paths if p.resolve() not in _alerted_conflict_paths]
    if not new_paths:
        return
    for p in new_paths:
        _alerted_conflict_paths.add(p.resolve())

    names = ", ".join(p.name for p in new_paths)
    logger.warning("Sync-conflict file(s) detected: %s", names)
    await asyncio.to_thread(
        send_gotify,
        "Syncthing conflict file(s) detected",
        f"{len(new_paths)} conflict file(s) need manual resolution: {names}",
        5,
    )


# ---------------------------------------------------------------------------
# Reconciliation — the correctness guarantee
# ---------------------------------------------------------------------------

async def reconcile_vault(memory: MemoryStore) -> None:
    """
    Full sweep: index anything unindexed or changed, drop anything
    orphaned, and catch up on any Inbox files left over from downtime.
    Safe to call repeatedly (idempotent), and safe to call on demand.
    """
    try:
        vault.ensure_vault_dirs()

        indexed = memory.list_indexed_notes()  # id -> metadata
        seen_ids = set()

        for path in vault.list_vault_notes():
            note = vault.parse_note(path)
            if note is None:
                continue
            seen_ids.add(note.id)
            current_mtime = path.stat().st_mtime
            indexed_meta = indexed.get(note.id)
            if indexed_meta is None or indexed_meta.get("mtime", 0) < current_mtime:
                await index_note_file(memory, path)

        # Orphans: indexed, but the file behind it is gone.
        for note_id in set(indexed) - seen_ids:
            memory.delete_note(note_id)

        # Anything left in Inbox from before the app was last running.
        for path in vault.list_inbox_files():
            await process_inbox_file(memory, path)

        await _alert_new_conflict_files(await asyncio.to_thread(_find_conflict_files))

        logger.info("Vault reconciliation complete: %d notes indexed.", len(seen_ids))

    except Exception as e:
        logger.error("Vault reconciliation failed: %s", e)
        await asyncio.to_thread(notify_error, "Vault reconciliation failed", e)


# ---------------------------------------------------------------------------
# Live watcher
# ---------------------------------------------------------------------------

async def watch_vault(memory: MemoryStore) -> None:
    """
    Live watcher — near-real-time updates on top of the reconciliation
    safety net above. watchfiles' awatch() already debounces bursts of
    filesystem events for us. Runs until cancelled.
    """
    root = vault.vault_root()
    vault.ensure_vault_dirs()
    inbox = vault.inbox_dir()

    async for changes in awatch(root):
        for change_type, changed_path_str in changes:
            path = Path(changed_path_str)

            if "sync-conflict" in path.name and change_type != Change.deleted and path.exists():
                await _alert_new_conflict_files([path])

            if vault.is_ignorable(path):
                continue

            try:
                if path.parent == inbox:
                    if change_type in (Change.added, Change.modified) and path.exists():
                        await process_inbox_file(memory, path)

                elif path.parent == root or vault.is_project_dir(path.parent):
                    if change_type in (Change.added, Change.modified) and path.exists():
                        await index_note_file(memory, path)
                    elif change_type == Change.deleted:
                        rel_path = str(path.relative_to(root))
                        await asyncio.to_thread(memory.delete_note_by_path, rel_path)

            except Exception as e:
                logger.error("Vault watcher failed handling %s: %s", path, e)
                await asyncio.to_thread(notify_error, f"Vault watcher failed on {path.name}", e)
