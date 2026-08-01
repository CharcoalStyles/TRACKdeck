#!/usr/bin/env bash
# reset_knowledge.sh
#
# Wipes the assistant's accumulated memory: conversation recall, the
# notes search index, and short-term thread checkpoints. Run from the
# project root.
#
# Handles both deployment modes, since the code uses relative paths that
# resolve differently depending on where the process runs from:
#   - Local (`uv run uvicorn ...`)  -> ./chroma_db, ./memory.db
#   - Docker (`docker compose up`)  -> ./data/chroma_db, ./data/memory.db
# Whichever of these actually exist on disk get wiped; the other is just
# skipped.
#
# onboarding_complete.flag (see utils/onboarding_state.py) is wiped
# alongside memory.db, not treated as durable state — it reflects whether
# the "onboarding" thread's conversation reached a natural conclusion, and
# that conversation's history lives in memory.db, which this script always
# clears. Leaving the flag standing after memory.db is wiped would mean
# static/profile.html defaults to the Profile Q&A view over an onboarding
# thread that no longer has any history — an inconsistent state.
#
# The Obsidian vault (your actual notes, About Me, Inbox) is NOT touched
# by default. It's synced live to every device you've paired via
# Syncthing — deleting it here would delete it everywhere once sync
# runs. Pass --vault if you genuinely want that too.
#
# checkins.db (mental-health check-in history, see utils/checkins_store.py)
# and device_errors.db (device error history, see utils/device_errors_store.py)
# are also NOT touched, deliberately and unconditionally — they're
# structured logs meant to persist for future trend/digest use, not
# disposable state like Chroma/memory.db are.
#
# settings.db (standing app-level toggles, see utils/settings_store.py) is
# likewise NOT touched — it's durable configuration (timezone, digest
# time, Gotify credentials, etc.), not accumulated memory.
#
# The bundled Radicale calendar data (./data/radicale) is likewise NOT
# touched — it's real calendar events, the same "not disposable" category
# as the vault and checkins.db, not derived/rebuildable state.
#
# Usage:
#   ./reset_knowledge.sh                 reset memory/index/checkpoints only
#   ./reset_knowledge.sh --vault         also wipe the vault (dangerous, see above)
#   ./reset_knowledge.sh --dry-run       show what would be deleted, delete nothing
#   ./reset_knowledge.sh --vault --dry-run

set -euo pipefail

WIPE_VAULT=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --vault) WIPE_VAULT=true ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h)
            sed -n '2,33p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (use --help)"
            exit 1
            ;;
    esac
done

# --- Locate whichever paths actually exist -----------------------------

CHROMA_CANDIDATES=("./chroma_db" "./data/chroma_db")
MEMORY_DB_CANDIDATES=("./memory.db" "./data/memory.db")
ONBOARDING_FLAG_CANDIDATES=("./onboarding_complete.flag" "./data/onboarding_complete.flag")
RECEIVED_NOTES_DIR="./received_notes"

# Vault path: respect VAULT_PATH from .env if present, else the coded
# default (./data/vault), matching utils/vault.py exactly.
VAULT_DIR="./data/vault"
if [[ -f .env ]] && grep -q '^VAULT_PATH=' .env; then
    VAULT_DIR="$(grep '^VAULT_PATH=' .env | tail -1 | cut -d'=' -f2-)"
fi

found_chroma=()
for c in "${CHROMA_CANDIDATES[@]}"; do
    [[ -d "$c" ]] && found_chroma+=("$c")
done

found_memory_db=()
for m in "${MEMORY_DB_CANDIDATES[@]}"; do
    [[ -f "$m" ]] && found_memory_db+=("$m")
done

found_onboarding_flag=()
for o in "${ONBOARDING_FLAG_CANDIDATES[@]}"; do
    [[ -f "$o" ]] && found_onboarding_flag+=("$o")
done

# --- Report what will happen -------------------------------------------

echo "This will permanently delete:"
if [[ ${#found_chroma[@]} -eq 0 ]]; then
    echo "  - Chroma (conversations + notes index): none found, nothing to do"
else
    for c in "${found_chroma[@]}"; do
        echo "  - Chroma (conversations + notes index): $c"
    done
fi
if [[ ${#found_memory_db[@]} -eq 0 ]]; then
    echo "  - Thread checkpoints (memory.db): none found, nothing to do"
else
    for m in "${found_memory_db[@]}"; do
        echo "  - Thread checkpoints (memory.db): $m"
    done
fi
if [[ ${#found_onboarding_flag[@]} -eq 0 ]]; then
    echo "  - Onboarding-complete flag: none found, nothing to do"
else
    for o in "${found_onboarding_flag[@]}"; do
        echo "  - Onboarding-complete flag: $o (so the Profile page shows the onboarding interview again)"
    done
fi
if [[ -d "$RECEIVED_NOTES_DIR" ]]; then
    echo "  - Raw received voice recordings: $RECEIVED_NOTES_DIR/*"
fi
if $WIPE_VAULT; then
    echo "  - THE VAULT ITSELF: $VAULT_DIR"
    echo "    WARNING: this is synced live to every paired device via Syncthing."
    echo "    Deleting it here deletes your notes everywhere, once sync runs."
fi
echo
echo "In-memory state (active keyword-addressed threads, the current session)"
echo "is NOT covered by this script — that only clears by restarting the app,"
echo "since it was never written to disk in the first place."
echo

if $DRY_RUN; then
    echo "(dry run — nothing will actually be deleted)"
    exit 0
fi

echo "This cannot be undone."
read -r -p "Type 'reset' to confirm: " confirm
if [[ "$confirm" != "reset" ]]; then
    echo "Aborted — nothing was deleted."
    exit 1
fi

echo
echo "If the app (or docker compose) is currently running, stop it now —"
echo "deleting memory.db out from under an open connection can leave it in"
echo "a bad state."
read -r -p "Press Enter once it's stopped (or Ctrl+C to cancel)... "

echo

for c in "${found_chroma[@]}"; do
    echo "Wiping $c ..."
    rm -rf "${c:?}"
    mkdir -p "$c"
done

for m in "${found_memory_db[@]}"; do
    echo "Wiping $m ..."
    rm -f "${m:?}"
    touch "$m"   # keep it a FILE — a missing file can get bind-mounted as a directory instead
done

for o in "${found_onboarding_flag[@]}"; do
    echo "Clearing $o ..."
    rm -f "${o:?}"
    touch "$o"   # empty = not complete (utils/onboarding_state.py checks content, not just
                 # existence) — keep it a FILE, same reasoning as memory.db above, since it's
                 # a docker-compose bind mount too
done

if [[ -d "$RECEIVED_NOTES_DIR" ]]; then
    echo "Clearing $RECEIVED_NOTES_DIR ..."
    rm -rf "${RECEIVED_NOTES_DIR:?}"/*
fi

if $WIPE_VAULT; then
    echo "Wiping vault at $VAULT_DIR ..."
    rm -rf "${VAULT_DIR:?}"/*
    mkdir -p "${VAULT_DIR}/Inbox"
fi

echo
echo "Done. Start the app (or docker compose up) — everything reinitializes on startup."