#!/usr/bin/env bash
# setup_check.sh
# Verifies (and fixes) the runtime prerequisites the docker-compose
# build/mounts need that aren't already handled elsewhere: the Piper TTS
# voice model (baked into the image by the dockerfile's `COPY . .`, so it
# has to exist on the host *before* `docker compose up --build`); the
# memory.db/reminders.db/checkins.db/alert_sounds.db/device_errors.db/
# onboarding_complete.flag/chroma_db paths that docker-compose expects to
# already exist as the right file types; the syncthing-config/vault/
# radicale directories (must exist as this user *before* `docker compose
# up`, or Docker auto-creates them as root on first run and the
# syncthing/caldav containers can't write to them); and PUID/PGID in
# .env.docker (must match this user, or Syncthing can't write its config).
#
# Only needs bash + curl — no uv/python/piper-tts required on the host,
# since the voice model is fetched directly from its Hugging Face URL.
#
# Safe to re-run — every step is idempotent.

set -euo pipefail

MODEL_DIR=".models"
VOICE_NAME="en_US-lessac-medium"
ONNX_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx"
JSON_PATH="${MODEL_DIR}/${VOICE_NAME}.onnx.json"
# Matches piper-tts's own download_voices.py URL_FORMAT for this voice
# (lang_family=en, lang_code=en_US, voice_name=lessac, voice_quality=medium).
VOICE_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

echo "== 1. Piper TTS voice model =="
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
echo "== 2. memory.db / reminders.db / checkins.db / alert_sounds.db / device_errors.db /"
echo "      onboarding_complete.flag / chroma_db (docker-compose bind mounts) =="
DATA_DIR="./data"
MEMORY_DB="${DATA_DIR}/memory.db"
REMINDERS_DB="${DATA_DIR}/reminders.db"
CHECKINS_DB="${DATA_DIR}/checkins.db"
ALERT_SOUNDS_DB="${DATA_DIR}/alert_sounds.db"
ALERT_SOUNDS_DIR="${DATA_DIR}/alert_sounds"
DEVICE_ERRORS_DB="${DATA_DIR}/device_errors.db"
ONBOARDING_FLAG="${DATA_DIR}/onboarding_complete.flag"
CHROMA_DIR="${DATA_DIR}/chroma_db"
HF_CACHE_DIR="${DATA_DIR}/hf_cache"

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

if [[ -d "$CHECKINS_DB" ]]; then
    echo "  ERROR: $CHECKINS_DB exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$CHECKINS_DB'"
    exit 1
elif [[ -f "$CHECKINS_DB" ]]; then
    echo "  OK: $CHECKINS_DB already exists as a file."
else
    echo "  Creating empty $CHECKINS_DB so Docker mounts it as a file..."
    touch "$CHECKINS_DB"
fi

if [[ -d "$ALERT_SOUNDS_DB" ]]; then
    echo "  ERROR: $ALERT_SOUNDS_DB exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$ALERT_SOUNDS_DB'"
    exit 1
elif [[ -f "$ALERT_SOUNDS_DB" ]]; then
    echo "  OK: $ALERT_SOUNDS_DB already exists as a file."
else
    echo "  Creating empty $ALERT_SOUNDS_DB so Docker mounts it as a file..."
    touch "$ALERT_SOUNDS_DB"
fi

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

if [[ -d "$DEVICE_ERRORS_DB" ]]; then
    echo "  ERROR: $DEVICE_ERRORS_DB exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$DEVICE_ERRORS_DB'"
    exit 1
elif [[ -f "$DEVICE_ERRORS_DB" ]]; then
    echo "  OK: $DEVICE_ERRORS_DB already exists as a file."
else
    echo "  Creating empty $DEVICE_ERRORS_DB so Docker mounts it as a file..."
    touch "$DEVICE_ERRORS_DB"
fi

if [[ -d "$ONBOARDING_FLAG" ]]; then
    echo "  ERROR: $ONBOARDING_FLAG exists but is a DIRECTORY, not a file."
    echo "         This happens when docker compose was run before this file existed."
    echo "         Remove it and re-run this script: rm -r '$ONBOARDING_FLAG'"
    exit 1
elif [[ -f "$ONBOARDING_FLAG" ]]; then
    echo "  OK: $ONBOARDING_FLAG already exists as a file."
else
    echo "  Creating empty $ONBOARDING_FLAG so Docker mounts it as a file..."
    touch "$ONBOARDING_FLAG"
fi

if [[ -d "$CHROMA_DIR" ]]; then
    echo "  OK: $CHROMA_DIR already exists as a directory."
else
    echo "  Creating $CHROMA_DIR..."
    mkdir -p "$CHROMA_DIR"
fi

if [[ -d "$HF_CACHE_DIR" ]]; then
    echo "  OK: $HF_CACHE_DIR already exists as a directory."
else
    echo "  Creating $HF_CACHE_DIR (Hugging Face cache for the faster-whisper model,"
    echo "  so it persists across rebuilds instead of re-downloading every time)..."
    mkdir -p "$HF_CACHE_DIR"
fi

echo
echo "== 3. syncthing-config / vault / radicale directories =="
echo "      (must exist before 'docker compose up', or Docker auto-creates"
echo "      them as root on first run and the containers can't write to them)"
SYNCTHING_CONFIG_DIR="${DATA_DIR}/syncthing-config"
VAULT_DIR="${DATA_DIR}/vault"
RADICALE_CONFIG_DIR="${DATA_DIR}/radicale/config"
RADICALE_DATA_DIR="${DATA_DIR}/radicale/data"

for dir in "$SYNCTHING_CONFIG_DIR" "$VAULT_DIR" "$RADICALE_CONFIG_DIR" "$RADICALE_DATA_DIR"; do
    if [[ -d "$dir" ]]; then
        echo "  OK: $dir already exists."
    else
        echo "  Creating $dir..."
        mkdir -p "$dir"
    fi
done

echo
echo "== 4. PUID/PGID (docker-compose.yml's syncthing service) =="
ENV_DOCKER=".env.docker"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

if [[ ! -f "$ENV_DOCKER" ]]; then
    echo "  SKIP: $ENV_DOCKER doesn't exist yet — copy .env.example to $ENV_DOCKER"
    echo "        and re-run this script so PUID/PGID can be set automatically."
elif grep -q '^PUID=' "$ENV_DOCKER" && grep -q '^PGID=' "$ENV_DOCKER"; then
    echo "  OK: PUID/PGID already set in $ENV_DOCKER (left as-is)."
else
    echo "  Setting PUID=$HOST_UID / PGID=$HOST_GID in $ENV_DOCKER (matches this user,"
    echo "  who owns the directories just created above)..."
    grep -q '^PUID=' "$ENV_DOCKER" || printf 'PUID=%s\n' "$HOST_UID" >> "$ENV_DOCKER"
    grep -q '^PGID=' "$ENV_DOCKER" || printf 'PGID=%s\n' "$HOST_GID" >> "$ENV_DOCKER"
fi

echo
echo "All prerequisites are in place."
echo
echo "Note: the bundled Radicale calendar service (docker-compose.yml's"
echo "\`caldav\`) is fully self-provisioning — it needs no setup here. Just set"
echo "CALDAV_USERNAME/CALDAV_PASSWORD/CALDAV_URL in .env.docker (same as any"
echo "other secret in that file) and \`docker compose --env-file .env.docker up\`"
echo "handles the rest."
echo "See README's \"First-run calendar setup\" for details."