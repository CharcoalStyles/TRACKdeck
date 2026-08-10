# Builds the React SPA (frontend/) in an isolated stage — Node itself
# never ends up in the final runtime image below, just the static
# dist/ output main.py's catch-all route (serve_spa) serves.
FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Use the official UV image which comes with UV pre-installed
# Pin to a specific Python version for reproducibility
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install ffmpeg (needed by faster-whisper for audio decoding)
# bookworm-slim is Debian 12, so ffmpeg is in the standard apt repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# docker-compose.yml bind-mounts many individual files/dirs under
# /app/data/ (memory.db, chroma_db/, ...) but never /app/data itself —
# and .dockerignore excludes data/ from the build context entirely, so
# without this the directory doesn't exist in the image. Docker would
# then auto-create it as root the moment the bind mounts are set up, at
# container-start, before the app (running as an arbitrary non-root UID
# via docker-compose.yml's `user:`) ever runs — and sqlite can't create
# its -journal/-wal files in a directory it can't write to ("attempt to
# write a readonly database"), even though memory.db itself is writable.
RUN mkdir -p /app/data && chmod 777 /app/data

# faster-whisper pulls its model from Hugging Face on first use (see
# utils/transcription.py) and caches it here. Left at the default location
# under /root so docker-compose.yml can bind-mount it to a host path and
# make it survive rebuilds/recreations instead of re-downloading every time.
# docker-compose.yml runs this image as a non-root UID (docker-compose.yml's
# `user:`), and /root is 700 by default — without opening it up, that UID
# couldn't even traverse into /root to reach the bind-mounted cache dir.
ENV HF_HOME=/root/.cache/huggingface
RUN chmod 755 /root

# uv also needs a cache dir, and (like HF_HOME above) the non-root UID
# docker-compose.yml runs this container as has no $HOME, so uv would
# otherwise fall back to the unwritable /.cache/uv. /tmp is world-writable
# regardless of UID, so point it there instead of chmod'ing another dir.
ENV UV_CACHE_DIR=/tmp/uv-cache

# huggingface_hub's Xet chunked-download backend (hf-xet, pulled in
# transitively) can hang retrying forever on networks that can reach
# huggingface.co but not Xet's separate CAS storage endpoints. Force the
# plain HTTP resolve/download path instead, which is what setup_check.sh's
# curl-based Piper download already relies on and is known to work here.
ENV HF_HUB_DISABLE_XET=1

# Copy dependency files first so Docker can cache the install layer
# and skip it on rebuilds when only app code has changed
COPY pyproject.toml uv.lock ./

# --frozen ensures the lockfile is respected exactly
# --no-dev skips any dev dependencies if you add them later
RUN uv sync --frozen --no-dev

# This build step runs as root, so it just populated UV_CACHE_DIR with
# root-owned files at root's default (non-world-writable) permissions —
# /tmp being 1777 itself didn't make what's already inside it writable.
# Open it up recursively so the non-root runtime UID can still use the
# cache (e.g. to revalidate the lockfile) without hitting the same
# permission error this whole cache dir was added to avoid.
RUN chmod -R 1777 /tmp/uv-cache

# .dockerignore excludes .venv (among other things) so this doesn't
# overwrite the venv uv sync just built for the container's platform.
COPY . .

# Pull in just the built SPA output from the frontend-build stage above —
# frontend/node_modules and frontend/src never touch this image.
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Run uvicorn via uv so it uses the project's installed packages.
# --no-sync: the venv above was already built exactly per the lockfile
# (--frozen --no-dev); without this, `uv run` re-syncs on every startup
# and — lacking --no-dev this time — tries to add dev deps (pytest etc)
# into .venv, which is root-owned from the build step and unwritable by
# the non-root runtime UID (docker-compose.yml's `user:`).
CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]