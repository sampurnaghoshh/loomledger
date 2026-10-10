#!/usr/bin/env bash
# Wipe and rebuild the demo database: same data, same numbers, every time.
# Run this before every rehearsal and right before going on stage.
#
#   ./scripts/reset_demo.sh                    reset (extra args go to the seed, e.g. --anchor 2026-10-12)
#   ./scripts/reset_demo.sh --smoke [URL]      rehearsal check: reset -> walk the whole demo over HTTP -> reset
#                                              (backend must be running, default URL http://localhost:8000)
# Windows: .\scripts\reset_demo.ps1 [-Smoke] [-Url ...] [-Anchor ...]
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/loomledger}"
PY="${PYTHON:-python}"

smoke=""
url="http://localhost:8000"
seed_args=()
while [ $# -gt 0 ]; do
    case "$1" in
        --smoke)
            smoke=1
            if [ $# -gt 1 ] && [[ "$2" != --* ]]; then url="$2"; shift; fi ;;
        *) seed_args+=("$1") ;;
    esac
    shift
done

reset() { "$PY" -m seed.seed ${seed_args[@]+"${seed_args[@]}"}; }

reset
if [ -n "$smoke" ]; then
    status=0
    "$PY" -m scripts.demo_smoke "$url" || status=$?
    echo "Resetting again so the stage starts clean..."
    reset
    exit "$status"
fi
