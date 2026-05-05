#!/usr/bin/env bash
# Convenience launcher: run backend with verbose logs enabled.
# CONCEPT: This keeps debugging a single command without remembering env vars.
# It also avoids editing code just to turn logs on/off.
# Use this for local dev; production should tune env vars explicitly.
set -euo pipefail

export HER_VOICE_TIMING_LOG="${HER_VOICE_TIMING_LOG:-1}"
export HER_CONVO_LOG="${HER_CONVO_LOG:-1}"

exec bash "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/run-backend.sh"

