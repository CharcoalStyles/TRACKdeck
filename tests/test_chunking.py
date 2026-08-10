from agent.memory import CHUNK_MAX_CHARS, _group_chunks, chunk_text


def test_short_text_is_a_single_unoverlapped_chunk():
    pairs = chunk_text("just a short note")
    assert len(pairs) == 1
    embed_text, stored_text = pairs[0]
    assert embed_text == stored_text == "just a short note"


def test_long_text_splits_and_reassembles_exactly():
    paragraphs = [f"Paragraph {i} " + "word " * 80 for i in range(10)]
    text = "\n\n".join(paragraphs)
    pairs = chunk_text(text)
    assert len(pairs) > 1
    for _, stored_text in pairs:
        assert len(stored_text) <= CHUNK_MAX_CHARS
    assert "\n\n".join(stored_text for _, stored_text in pairs) == text


def test_oversized_single_paragraph_is_hard_split():
    text = "x" * (CHUNK_MAX_CHARS * 3 + 10)
    pairs = chunk_text(text)
    assert len(pairs) == 4
    for _, stored_text in pairs:
        assert len(stored_text) <= CHUNK_MAX_CHARS
    assert "".join(stored_text for _, stored_text in pairs) == text


def test_embed_text_carries_previous_chunk_tail():
    paragraphs = [f"Paragraph {i} " + "word " * 80 for i in range(10)]
    text = "\n\n".join(paragraphs)
    pairs = chunk_text(text)
    assert len(pairs) > 1
    for (_, prev_stored), (embed_text, _) in zip(pairs, pairs[1:]):
        assert embed_text.startswith(prev_stored[-120:])


def test_group_chunks_groups_by_metadata_key_in_order():
    ids = ["a::1", "a::0", "b::0"]
    documents = ["second", "first", "only"]
    metadatas = [
        {"note_id": "a", "chunk_index": 1},
        {"note_id": "a", "chunk_index": 0},
        {"note_id": "b", "chunk_index": 0},
    ]
    groups = _group_chunks(ids, documents, metadatas, "note_id")
    assert groups["a"]["text"] == "first\n\nsecond"
    assert groups["b"]["text"] == "only"


def test_group_chunks_falls_back_to_id_for_legacy_rows():
    ids = ["legacy-note-id"]
    documents = ["whole legacy note, no chunk metadata"]
    metadatas = [{"title": "Old Note"}]
    groups = _group_chunks(ids, documents, metadatas, "note_id")
    assert set(groups) == {"legacy-note-id"}
    assert groups["legacy-note-id"]["text"] == "whole legacy note, no chunk metadata"
