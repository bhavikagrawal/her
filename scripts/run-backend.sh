#!/usr/bin/env bash
# This script starts the Python WebSocket process for local development.
# It lives in `scripts/` so Tauri's `beforeDevCommand` can find a single entry point.
# The app root is derived from the script path, so you can run Tauri from any CWD.
# It prefers the project venv (after `setup.sh`) so `websockets` and later ML deps are found.
# PYTHONPATH must be the repo root so `import backend....` works when running `backend/main.py` as a file.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # CONCEPT: "sourcing" runs the venv's shell script in *this* process so `python` points at the venv.
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
# Default to verbose logs in dev (can be overridden by exporting 0/1 before launch).
export HER_VOICE_TIMING_LOG="${HER_VOICE_TIMING_LOG:-1}"
export HER_CONVO_LOG="${HER_CONVO_LOG:-1}"
exec python3 backend/main.py
