#!/usr/bin/env bash
# reset_knowledge.sh
#
# Wipes the assistant's accumulated memory: conversation recall, the
# notes search index, and short-term thread checkpoints — then re-runs
# setup.sh to recreate empty placeholders in their place (same file/
# directory TYPE Docker's bind mounts expect — see setup.sh's own
# comments). setup.sh never overwrites .env/.env.docker/.env.example, so
# this never touches those either. Run from the project root.
#
# Every store (settings.db, memory.db, chroma_db, ...) resolves its path
# as "data/<name>" relative to cwd, so local (`uv run uvicorn ...`) and
# Docker (`docker compose up`) both always land on the same ./data/
# location — nothing candidate/deployment-mode-specific to search for.
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

CHROMA_DIR="./data/chroma_db"
MEMORY_DB="./data/memory.db"
ONBOARDING_FLAG="./data/onboarding_complete.flag"
ONBOARDING_BASICS_FLAG="./data/onboarding_basics.flag"
RECEIVED_NOTES_DIR="./received_notes"

# Vault path: respect VAULT_PATH from .env if present, else the coded
# default (./data/vault), matching utils/vault.py exactly.
VAULT_DIR="./data/vault"
if [[ -f .env ]] && grep -q '^VAULT_PATH=' .env; then
    VAULT_DIR="$(grep '^VAULT_PATH=' .env | tail -1 | cut -d'=' -f2-)"
fi

found_chroma=()
[[ -d "$CHROMA_DIR" ]] && found_chroma+=("$CHROMA_DIR")

found_memory_db=()
[[ -f "$MEMORY_DB" ]] && found_memory_db+=("$MEMORY_DB")

found_onboarding_flag=()
[[ -f "$ONBOARDING_FLAG" ]] && found_onboarding_flag+=("$ONBOARDING_FLAG")
[[ -f "$ONBOARDING_BASICS_FLAG" ]] && found_onboarding_flag+=("$ONBOARDING_BASICS_FLAG")

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
done

for m in "${found_memory_db[@]}"; do
    echo "Wiping $m ..."
    rm -f "${m:?}"
done

for o in "${found_onboarding_flag[@]}"; do
    echo "Clearing $o ..."
    rm -f "${o:?}"
done

if [[ -d "$RECEIVED_NOTES_DIR" ]]; then
    echo "Clearing $RECEIVED_NOTES_DIR ..."
    rm -rf "${RECEIVED_NOTES_DIR:?}"/*
fi

if $WIPE_VAULT; then
    echo "Wiping vault at $VAULT_DIR ..."
    rm -rf "${VAULT_DIR:?}"/*
fi

echo
echo "Re-running setup.sh to recreate empty placeholders (chroma_db, memory.db,"
echo "onboarding_complete.flag, vault/Inbox, ...) as this user — it never touches"
echo ".env/.env.docker/.env.example, so nothing configured is affected."
echo
./setup.sh

echo
echo "Done. Start the app (or docker compose up) — everything reinitializes on startup."