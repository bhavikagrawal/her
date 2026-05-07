#!/usr/bin/env bash
# Prints MemPalace paths and drawer counts for HER (no WebSocket required).
# Uses the same PYTHONPATH layout as run-backend.sh so `backend.*` imports resolve.
# Run after `setup.sh` from the repo root: `bash scripts/her_memory_status.sh`
# Output is JSON for easy piping to jq; see ENVIRONMENT.md for wipe instructions.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
exec python3 -c "import json; from backend.memory.mempalace_adapter import status_dict; print(json.dumps(status_dict(), indent=2))"
