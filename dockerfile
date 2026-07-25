# Use the official UV image which comes with UV pre-installed
# Pin to a specific Python version for reproducibility
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install ffmpeg (needed by faster-whisper for audio decoding)
# bookworm-slim is Debian 12, so ffmpeg is in the standard apt repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

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