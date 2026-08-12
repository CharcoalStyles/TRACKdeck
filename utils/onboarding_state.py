"""
utils/onboarding_state.py
---------------------------
Whether the guided onboarding interview has been marked complete
(agent/tools/general.py's mark_onboarding_complete tool), read by
static/profile.html to decide whether to default to the onboarding
interview view or the profile Q&A view.

A single sentinel file rather than a new sqlite table for one boolean —
deliberately NOT part of agent/settings.py's in-memory Settings class:
that class resets on every container rebuild (not just a host restart),
and losing this specific flag has a real user-visible consequence (the
merged page silently reverts to the interview view) unlike the other
in-memory settings fields, which just fall back to a reasonable default.
Same "small persisted marker gets its own bind-mounted file" treatment
as memory.db/checkins.db.

Completion is signalled by the file's *content* (empty vs non-empty),
not merely its existence — deliberately, so the file itself can always
exist on disk. reset_knowledge.sh clears completion by truncating this
file rather than removing it, same as it does for memory.db, since the
file path is a docker-compose bind mount: if it goes missing on the
host, Docker creates a directory there instead on the next
`docker compose up`, and sqlite/file opens against that path start
failing (setup_check.sh exists to guard against exactly that class of
bug for the sqlite-backed stores).
"""
from __future__ import annotations

import os

FLAG_PATH = "./data/onboarding_complete.flag"

# Same treatment, one step earlier: whether the basics form (name, location,
# people, etc.) has been submitted at least once. Distinct from FLAG_PATH
# above, which marks the full guided-interview conversation as done.
BASICS_FLAG_PATH = "./data/onboarding_basics.flag"


def is_onboarding_complete() -> bool:
    return os.path.exists(FLAG_PATH) and os.path.getsize(FLAG_PATH) > 0


def mark_onboarding_complete() -> None:
    with open(FLAG_PATH, "w") as f:
        f.write("1")


def is_basics_complete() -> bool:
    return os.path.exists(BASICS_FLAG_PATH) and os.path.getsize(BASICS_FLAG_PATH) > 0


def mark_basics_complete() -> None:
    with open(BASICS_FLAG_PATH, "w") as f:
        f.write("1")


def clear_onboarding_complete() -> None:
    with open(FLAG_PATH, "w"):
        pass


def clear_basics_complete() -> None:
    with open(BASICS_FLAG_PATH, "w"):
        pass
