#!/usr/bin/env bash
# Downloads whisper.cpp's `ggml-medium.bin` into `data/models/whisper/` for Phase 1 STT.
# The file is large (~1.5GB) so `setup.sh` only runs this when you opt in via an env flag.
# Uses Hugging Face "resolve" URLs so the filename stays stable across whisper.cpp releases.
# Safe to rerun: `curl -C -` resumes partial downloads when supported by the server/CDN.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
TARGET_DIR="${ROOT}/data/models/whisper"
mkdir -p "${TARGET_DIR}"

DEST="${TARGET_DIR}/ggml-medium.bin"
if [[ -f "${DEST}" ]]; then
  echo "Already present: ${DEST}"
  exit 0
fi

URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"

echo "Downloading ggml-medium.bin (large) → ${DEST}"
echo "If this fails, download manually from Hugging Face and place the file at:"
echo "  ${DEST}"

curl --fail --location --continue-at - --progress-bar "${URL}" -o "${DEST}.partial"
mv "${DEST}.partial" "${DEST}"
echo "Whisper medium model ready at ${DEST}"
