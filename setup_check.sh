#!/usr/bin/env bash
# setup_check.sh
# Verifies (and fixes) the two runtime prerequisites that don't come from
# `uv sync`: the Piper TTS voice model, and the memory.db/reminders.db/
# chroma_db paths that docker-compose expects to already exist as the
# right file types.
#
# Safe to re-run — every step is idempotent.

set -euo pipefail

MODEL_DIR=".models"
VOICE_NAME="en_US-lessac-medium"
ONNX_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx"
JSON_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx.json"

echo "== 1. Piper TTS voice model =="
mkdir -p "$MODEL_DIR"

if [[ -f "$ONNX_PATH" && -f "$JSON_PATH" ]]; then
    echo "  OK: $ONNX_PATH and $JSON_PATH already present."
else
    echo "  Missing model files — downloading '$VOICE_NAME' via piper.download_voices..."
    # Requires piper-tts to be installed (it's in pyproject.toml already).
    # If you're using uv: `uv run python -m piper.download_voices ...`
    python3 -m piper.download_voices --data-dir "$MODEL_DIR" "$VOICE_NAME"

    if [[ -f "$ONNX_PATH" && -f "$JSON_PATH" ]]; then
        echo "  Downloaded successfully."
    else
        echo "  ERROR: download ran but expected files still missing. Check filenames"
        echo "         in $MODEL_DIR/ — the downloader may have used a slightly"
        echo "         different name than routes/synth.py expects."
        exit 1
    fi
fi

echo
echo "== 2. memory.db / reminders.db / chroma_db (docker-compose bind mounts) =="
DATA_DIR="./data"
MEMORY_DB="${DATA_DIR}/memory.db"
REMINDERS_DB="${DATA_DIR}/reminders.db"
CHROMA_DIR="${DATA_DIR}/chroma_db"

mkdir -p "$DATA_DIR"

# docker-compose.yml bind-mounts ./data/memory.db and ./data/reminders.db
# as FILEs into the container. If either doesn't exist on the host yet,
# Docker will create it as a DIRECTORY instead, and sqlite will fail to
# open it.
if [[ -d "$MEMORY_DB" ]]; then
    echo "  ERROR: $MEMORY_DB exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$MEMORY_DB'"
    exit 1
elif [[ -f "$MEMORY_DB" ]]; then
    echo "  OK: $MEMORY_DB already exists as a file."
else
    echo "  Creating empty $MEMORY_DB so Docker mounts it as a file..."
    touch "$MEMORY_DB"
fi

if [[ -d "$REMINDERS_DB" ]]; then
    echo "  ERROR: $REMINDERS_DB exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$REMINDERS_DB'"
    exit 1
elif [[ -f "$REMINDERS_DB" ]]; then
    echo "  OK: $REMINDERS_DB already exists as a file."
else
    echo "  Creating empty $REMINDERS_DB so Docker mounts it as a file..."
    touch "$REMINDERS_DB"
fi

if [[ -d "$CHROMA_DIR" ]]; then
    echo "  OK: $CHROMA_DIR already exists as a directory."
else
    echo "  Creating $CHROMA_DIR..."
    mkdir -p "$CHROMA_DIR"
fi

echo
echo "All prerequisites are in place."