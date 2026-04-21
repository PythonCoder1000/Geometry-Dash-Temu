#!/usr/bin/env bash
# Dev helper: start the Trigonometry Sprint server locally.
#   scripts/run_server.sh
# Install deps once with:
#   pip install -r requirements-server.txt
set -euo pipefail
cd "$(dirname "$0")/.."
exec uvicorn server.app:app --reload --port 8000
