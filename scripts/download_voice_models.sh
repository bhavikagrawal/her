#!/usr/bin/env bash
# Pulls Kokoro ONNX weights into `data/models/kokoro/` so TTS works after a clean git clone.
# Whisper and Piper binaries are installed separately — this script only grabs what PyPI omits.
# Safe to rerun: `curl` uses `-C -` compatible mode by re-downloading if prior file was partial.
# CONCEPT: Models are “big static assets”, so we keep them out of Git and fetch on demand.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
TARGET="${ROOT}/data/models/kokoro"
mkdir -p "${TARGET}"

BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  dest="${TARGET}/${f}"
  if [[ -f "${dest}" ]]; then
    echo "Already present: ${dest}"
    continue
  fi
  echo "Downloading ${f}…"
  curl --fail --location --progress-bar "${BASE_URL}/${f}" -o "${dest}.partial"
  mv "${dest}.partial" "${dest}"
done

echo "Kokoro models ready under ${TARGET}"
