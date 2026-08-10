#!/usr/bin/env bash
# setup.sh
# Bootstrap + prerequisite checker, in one idempotent script. Safe to run
# any time — on a fresh clone, or again later to fix a bind-mount/ownership
# problem — every step just verifies-or-fixes, nothing already in place is
# overwritten. Needs nothing but bash + curl on the host; the primary way
# to run this project is `docker compose up --build`, which brings its own
# Python/Node deps (the dockerfile runs `uv sync`/`npm ci` inside the image
# build) — this script only handles what has to exist on the host first:
#
#   1. Generates .env and .env.docker from .env.example, with real random
#      values for the three secrets the app refuses to start without
#      (API_TOKEN, DASHBOARD_PASSWORD, SESSION_SECRET_KEY)
#   2. Downloads the Piper TTS voice model
#   3. Creates the memory.db/reminders.db/.../chroma_db paths as the right
#      file TYPE (file vs directory) — docker-compose bind-mounts each of
#      these, and if one doesn't exist on the host yet, Docker creates it
#      as the wrong type (usually a directory) and the app fails to open it
#   4. Creates the vault/syncthing-config/radicale/received_notes
#      directories that must exist as this user *before* `docker compose
#      up`, or Docker auto-creates them as root and the containers can't
#      write to them
#   5. Sets PUID/PGID in .env.docker to this user, so the assistant and
#      syncthing containers run as (and write files as) you instead of root
#
# Usage:
#   ./setup.sh

set -euo pipefail

random_secret() {
    # /dev/urandom + od + tr — no openssl or other extra dependency, just
    # coreutils that ship on every Linux/macOS host already.
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

echo "== 1. .env / .env.docker =="

setup_env_file() {
    local target="$1"
    local vault_path="$2"   # ./data/vault for local dev, /app/vault inside the container

    if [[ -f "$target" ]]; then
        echo "  OK: $target already exists — leaving it untouched."
        return
    fi

    echo "  Creating $target from .env.example..."
    cp .env.example "$target"

    # Fill in the three secrets the app refuses to start without (see
    # README's "Running it" section) with real random values instead of
    # leaving the placeholders in place. -i.bak works identically on both
    # BSD/macOS and GNU sed.
    sed -i.bak \
        -e "s|^API_TOKEN=.*|API_TOKEN=$(random_secret)|" \
        -e "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=$(random_secret)|" \
        -e "s|^SESSION_SECRET_KEY=.*|SESSION_SECRET_KEY=$(random_secret)|" \
        -e "s|^VAULT_PATH=.*|VAULT_PATH=${vault_path}|" \
        "$target"
    rm -f "${target}.bak"

    echo "  Generated $target with random API_TOKEN/DASHBOARD_PASSWORD/SESSION_SECRET_KEY."
    echo "  Fill in CalDAV/Gotify/SMTP values yourself if/when you need those features."
}

setup_env_file ".env" "./data/vault"
setup_env_file ".env.docker" "/app/vault"

echo
echo "== 2. Piper TTS voice model =="
MODEL_DIR=".models"
VOICE_NAME="en_US-lessac-medium"
ONNX_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx"
JSON_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx.json"
# Matches piper-tts's own download_voices.py URL_FORMAT for this voice
# (lang_family=en, lang_code=en_US, voice_name=lessac, voice_quality=medium).
VOICE_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

mkdir -p "$MODEL_DIR"

if [[ -f "$ONNX_PATH" && -f "$JSON_PATH" ]]; then
    echo "  OK: $ONNX_PATH and $JSON_PATH already present."
else
    echo "  Missing model files — downloading '$VOICE_NAME' from Hugging Face..."
    if ! command -v curl >/dev/null 2>&1; then
        echo "  ERROR: 'curl' is required to download the voice model but isn't on PATH."
        exit 1
    fi
    curl -fL -o "$ONNX_PATH" "${VOICE_BASE_URL}/${VOICE_NAME}.onnx?download=true"
    curl -fL -o "$JSON_PATH" "${VOICE_BASE_URL}/${VOICE_NAME}.onnx.json?download=true"

    if [[ -f "$ONNX_PATH" && -f "$JSON_PATH" ]]; then
        echo "  Downloaded successfully."
    else
        echo "  ERROR: download ran but expected files still missing. Check filenames"
        echo "         in $MODEL_DIR/ — routes/synth.py expects exactly"
        echo "         '$VOICE_NAME.onnx' and '$VOICE_NAME.onnx.json'."
        exit 1
    fi
fi

echo
echo "== 3. memory.db / reminders.db / checkins.db / settings.db / alert_sounds.db /"
echo "      device_errors.db / recall_log.db / device_state.db / activity_log.db /"
echo "      onboarding_complete.flag / chroma_db (docker-compose bind mounts) =="
DATA_DIR="./data"
mkdir -p "$DATA_DIR"

# docker-compose.yml bind-mounts each *.db below as a FILE into the
# container. If it doesn't exist on the host yet, Docker creates it as a
# DIRECTORY instead, and sqlite fails to open it.
ensure_db_file() {
    local path="$1"
    if [[ -d "$path" ]]; then
        echo "  ERROR: $path exists but is a DIRECTORY, not a file."
        echo "         This happens when docker compose was run before this file existed."
        echo "         Remove it and re-run this script: rm -r '$path'"
        exit 1
    elif [[ -f "$path" ]]; then
        echo "  OK: $path already exists as a file."
    else
        echo "  Creating empty $path so Docker mounts it as a file..."
        touch "$path"
    fi
}

for db in memory.db reminders.db checkins.db settings.db alert_sounds.db \
          device_errors.db recall_log.db device_state.db activity_log.db \
          onboarding_complete.flag; do
    ensure_db_file "${DATA_DIR}/${db}"
done

ALERT_SOUNDS_DIR="${DATA_DIR}/alert_sounds"
if [[ -f "$ALERT_SOUNDS_DIR" ]]; then
    echo "  ERROR: $ALERT_SOUNDS_DIR exists but is a FILE, not a directory."
    echo "         Remove it and re-run this script: rm '$ALERT_SOUNDS_DIR'"
    exit 1
elif [[ -d "$ALERT_SOUNDS_DIR" ]]; then
    echo "  OK: $ALERT_SOUNDS_DIR already exists as a directory."
else
    echo "  Creating $ALERT_SOUNDS_DIR..."
    mkdir -p "$ALERT_SOUNDS_DIR"
fi

CHROMA_DIR="${DATA_DIR}/chroma_db"
if [[ -d "$CHROMA_DIR" ]]; then
    echo "  OK: $CHROMA_DIR already exists as a directory."
else
    echo "  Creating $CHROMA_DIR..."
    mkdir -p "$CHROMA_DIR"
fi

HF_CACHE_DIR="${DATA_DIR}/hf_cache"
if [[ -d "$HF_CACHE_DIR" ]]; then
    echo "  OK: $HF_CACHE_DIR already exists as a directory."
else
    echo "  Creating $HF_CACHE_DIR (Hugging Face cache for the faster-whisper model,"
    echo "  so it persists across rebuilds instead of re-downloading every time)..."
    mkdir -p "$HF_CACHE_DIR"
fi

echo
echo "== 4. vault / syncthing-config / radicale / received_notes directories =="
echo "      (must exist before 'docker compose up', or Docker auto-creates"
echo "      them as root on first run and the containers can't write to them)"
for dir in "${DATA_DIR}/vault/Inbox" "${DATA_DIR}/syncthing-config" \
           "${DATA_DIR}/radicale/config" "${DATA_DIR}/radicale/data" \
           "./received_notes"; do
    if [[ -d "$dir" ]]; then
        echo "  OK: $dir already exists."
    else
        echo "  Creating $dir..."
        mkdir -p "$dir"
    fi
done

echo
echo "== 5. PUID/PGID (docker-compose.yml's assistant + syncthing services) =="
ENV_DOCKER=".env.docker"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

if [[ ! -f "$ENV_DOCKER" ]]; then
    echo "  SKIP: $ENV_DOCKER doesn't exist yet — this shouldn't happen, since step 1"
    echo "        above creates it. Re-run this script."
elif grep -q '^PUID=' "$ENV_DOCKER" && grep -q '^PGID=' "$ENV_DOCKER"; then
    echo "  OK: PUID/PGID already set in $ENV_DOCKER (left as-is)."
else
    echo "  Setting PUID=$HOST_UID / PGID=$HOST_GID in $ENV_DOCKER (matches this user,"
    echo "  who owns the directories just created above)..."
    grep -q '^PUID=' "$ENV_DOCKER" || printf 'PUID=%s\n' "$HOST_UID" >> "$ENV_DOCKER"
    grep -q '^PGID=' "$ENV_DOCKER" || printf 'PGID=%s\n' "$HOST_GID" >> "$ENV_DOCKER"
fi

echo
echo "All set. Next steps:"
echo "  - Fill in CalDAV/Gotify/SMTP values in .env / .env.docker if you want those features."
echo "  - Full stack (primary):  docker compose --env-file .env.docker up --build"
echo "  - Local dev (needs uv):  uv run uvicorn main:app --reload"
echo "See README.md's \"Running it\" section for the rest."
echo
echo "Note: the bundled Radicale calendar service (docker-compose.yml's"
echo "\`caldav\`) is fully self-provisioning — it needs no setup here. Just set"
echo "CALDAV_USERNAME/CALDAV_PASSWORD/CALDAV_URL in .env.docker (same as any"
echo "other secret in that file) and \`docker compose --env-file .env.docker up\`"
echo "handles the rest."
echo "See README's \"First-run calendar setup\" for details."
