#!/usr/bin/env bash
# setup.sh
# One-time first-run bootstrap. The primary way to run this project is
# `docker compose up --build`, which brings its own dependencies (the
# dockerfile runs `uv sync` *inside* the image build) — this script only
# handles what has to exist on the host beforehand, and needs nothing but
# bash + curl to do it:
#
#   1. Generates .env and .env.docker from .env.example, with real random
#      values for the three secrets the app refuses to start without
#      (API_TOKEN, DASHBOARD_PASSWORD, SESSION_SECRET_KEY)
#   2. Creates the notes vault directory
#   3. Runs setup_check.sh (Piper voice model + docker-compose bind-mount
#      file/dir gotchas under ./data)
#
# Safe to re-run — existing .env/.env.docker are never overwritten, every
# other step is idempotent.
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
echo "== 2. Notes vault directory =="
mkdir -p "./data/vault/Inbox"
echo "  OK: ./data/vault/Inbox present."

echo
echo "== 3. Piper voice model + DB bind-mount files (setup_check.sh) =="
./setup_check.sh

echo
echo "All set. Next steps:"
echo "  - Fill in CalDAV/Gotify/SMTP values in .env / .env.docker if you want those features."
echo "  - Full stack (primary):  docker compose --env-file .env.docker up --build"
echo "  - Local dev (needs uv):  uv run uvicorn main:app --reload"
echo "See README.md's \"Running it\" section for the rest."
