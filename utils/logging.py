"""
utils/logging.py
-----------------
One place to configure stdlib logging for the whole app. Human-readable
text (timestamp + level + logger name), not JSON — this is a
single-instance, self-hosted tool where the primary way of reading logs
is `docker compose logs` or a terminal, not a log aggregator.

Call configure_logging() exactly once, as early as possible in main.py
(right after load_dotenv(), before importing modules that create module-
level loggers) so LOG_LEVEL is already read from the environment and every
logger created afterwards picks up the same handler/formatter via the
root logger.

Every other module gets its own logger via `logging.getLogger(__name__)`
rather than calling print() directly — that's what makes this greppable
by module (`agent.vault_watcher`, `jobs.digest`, ...) and filterable by
level.
"""
from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
