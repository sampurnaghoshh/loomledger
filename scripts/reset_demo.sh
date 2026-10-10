#!/usr/bin/env bash
# Wipe and rebuild a LoomLedger database: same data, same numbers, every time.
# Run this before every rehearsal and right before going on stage.
#
#   ./scripts/reset_demo.sh                    reset the demo DB ($DATABASE_URL, default .../loomledger)
#   ./scripts/reset_demo.sh --db-url URL       reset another database (created if missing)
#   ./scripts/reset_demo.sh --smoke [API]      reset -> walk the whole demo over HTTP against a RUNNING backend -> reset
#   ./scripts/reset_demo.sh --rehearsal        private rehearsal, leaves the demo DB and :8000 alone:
#                                              loomledger_rehearsal (created if missing) + its own backend on :8001
#                                              -> reset -> smoke -> stop that backend -> reset
#   other args go to the seed, e.g. --anchor 2026-10-12
# Windows: .\scripts\reset_demo.ps1 [-DatabaseUrl URL] [-Smoke [-Url API]] [-Rehearsal] [-Anchor DATE]
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
REHEARSAL_DB="postgresql://postgres:postgres@localhost:5432/loomledger_rehearsal"
REHEARSAL_PORT="${REHEARSAL_PORT:-8001}"

db_url="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/loomledger}"
custom_db=""
smoke=""
rehearsal=""
api="http://localhost:8000"
seed_args=()
while [ $# -gt 0 ]; do
    case "$1" in
        --db-url) db_url="$2"; custom_db=1; shift ;;
        --rehearsal) rehearsal=1 ;;
        --smoke)
            smoke=1
            if [ $# -gt 1 ] && [[ "$2" != --* ]]; then api="$2"; shift; fi ;;
        *) seed_args+=("$1") ;;
    esac
    shift
done

if [ -n "$rehearsal" ]; then
    [ -n "$custom_db" ] || db_url="$REHEARSAL_DB"
    api="http://localhost:$REHEARSAL_PORT"
    smoke=1
fi
export DATABASE_URL="$db_url"
"$PY" -m scripts.ensure_db "$DATABASE_URL" || echo "(could not check/create the database - continuing)"
echo "database: ${DATABASE_URL##*/}"

reset() { "$PY" -m seed.seed ${seed_args[@]+"${seed_args[@]}"}; }

reset
[ -n "$smoke" ] || exit 0

backend=""
if [ -n "$rehearsal" ]; then
    if "$PY" -c "import httpx,sys; httpx.get('$api/api/health', timeout=2); sys.exit(0)" 2>/dev/null; then
        echo "something is already answering on $api — stop it or set REHEARSAL_PORT" >&2
        exit 2
    fi
    "$PY" -m uvicorn app.main:app --port "$REHEARSAL_PORT" --log-level warning &
    backend=$!
    trap '[ -n "$backend" ] && kill "$backend" 2>/dev/null || true' EXIT
    for _ in $(seq 1 40); do
        "$PY" -c "import httpx,sys; sys.exit(0 if httpx.get('$api/api/health', timeout=2).status_code == 200 else 1)" \
            2>/dev/null && break
        sleep 0.5
    done
fi

status=0
"$PY" -m scripts.demo_smoke "$api" || status=$?
if [ -n "$backend" ]; then kill "$backend" 2>/dev/null || true; wait "$backend" 2>/dev/null || true; backend=""; fi
echo "Resetting ${DATABASE_URL##*/} again so it starts clean..."
reset
exit "$status"
