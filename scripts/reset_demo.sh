#!/usr/bin/env bash
# Wipe and rebuild the demo database: same data, same numbers, every time.
# Run this before every rehearsal and right before going on stage.
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/loomledger}"
python -m seed.seed "$@"
