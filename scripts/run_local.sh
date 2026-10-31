#!/bin/sh
# Starts Clyvexa on this computer: the private database, then the app at
# http://127.0.0.1:8765 (website) and http://127.0.0.1:8765/app (bill checker).
# Settings and keys come from .env.dev (git-ignored). Stop with Ctrl+C.
set -e
cd "$(dirname "$0")/.."
scripts/dev_db.sh status >/dev/null 2>&1 || scripts/dev_db.sh start  # start the database unless it is already running
[ -d frontend/out ] || (cd frontend && npm run build)
set -a; . ./.env.dev; set +a
echo "Clyvexa: http://127.0.0.1:8765/app"
exec .venv/bin/python -W ignore -m uvicorn --factory billchecker.api:app_from_env --host 127.0.0.1 --port 8765
