# Use the official UV image which comes with UV pre-installed
# Pin to a specific Python version for reproducibility
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install ffmpeg (needed by faster-whisper for audio decoding)
# bookworm-slim is Debian 12, so ffmpeg is in the standard apt repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# faster-whisper pulls its model from Hugging Face on first use (see
# utils/transcription.py) and caches it here. Left at the default location
# under /root so docker-compose.yml can bind-mount it to a host path and
# make it survive rebuilds/recreations instead of re-downloading every time.
ENV HF_HOME=/root/.cache/huggingface

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

# .dockerignore excludes .venv (among other things) so this doesn't
# overwrite the venv uv sync just built for the container's platform.
COPY . .

# Run uvicorn via uv so it uses the project's installed packages
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]