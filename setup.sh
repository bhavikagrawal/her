#!/usr/bin/env bash
# One-shot bootstrap for HER on a Mac that already has Homebrew installed.
# Installs Rust (Tauri), Python 3.12+ (Kokoro needs ≥3.10), Whisper, voice deps, and Tauri CLI.
# Idempotent enough to re-run: existing `.venv` is reused; pip always upgrades to match `requirements.txt`.
# CONCEPT: A virtual environment (`venv`) sandboxes pip packages into `.venv/` beside the code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required first: https://brew.sh"
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Install Xcode Command Line Tools: xcode-select --install"
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Installing Rust (provides cargo) via Homebrew…"
  brew install rust
fi

PYTHON_BIN=""
for ver in 3.13 3.12 3.11 3.10; do
  if command -v "python${ver}" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "python${ver}")"
    break
  fi
done
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "No Python 3.10+ found — installing python@3.12 via Homebrew…"
  brew install python@3.12
  PYTHON_BIN="$(command -v python3.12)"
fi

echo "Using interpreter: ${PYTHON_BIN}"

if [[ ! -d "${ROOT}/.venv" ]]; then
  echo "Creating virtual environment at ${ROOT}/.venv …"
  "$PYTHON_BIN" -m venv "${ROOT}/.venv"
else
  echo "Reusing existing venv at ${ROOT}/.venv"
fi
# shellcheck disable=SC1091
source "${ROOT}/.venv/bin/activate"

pip install --upgrade pip
pip install -r "${ROOT}/requirements.txt"

chmod +x "${ROOT}/scripts/run-backend.sh"
chmod +x "${ROOT}/scripts/download_voice_models.sh"
chmod +x "${ROOT}/scripts/download_whisper_medium.sh"
chmod +x "${ROOT}/scripts/her_memory_status.sh"

if [[ ! -f "${ROOT}/src-tauri/icons/icon.png" ]]; then
  echo "Writing placeholder src-tauri/icons/icon.png…"
  python "${ROOT}/scripts/generate_tauri_icon.py"
fi

echo "Fetching Kokoro ONNX weights (requires network)…"
bash "${ROOT}/scripts/download_voice_models.sh"

if ! command -v whisper-cli >/dev/null 2>&1 && ! command -v whisper >/dev/null 2>&1 && ! command -v main >/dev/null 2>&1; then
  echo "Installing whisper.cpp via Homebrew (provides `whisper-cli` on many installs)…"
  brew install whisper-cpp
fi

WHISPER_MODEL_PATH="${ROOT}/data/models/whisper/ggml-medium.bin"
if [[ ! -f "${WHISPER_MODEL_PATH}" ]]; then
  if [[ "${HER_FETCH_WHISPER_MODEL:-0}" == "1" ]]; then
    echo "HER_FETCH_WHISPER_MODEL=1 → downloading ggml-medium.bin (large download)…"
    bash "${ROOT}/scripts/download_whisper_medium.sh"
  else
    echo ""
    echo "Whisper model not present yet:"
    echo "  ${WHISPER_MODEL_PATH}"
    echo "To download automatically (large ~1.5GB), rerun:"
    echo "  HER_FETCH_WHISPER_MODEL=1 bash setup.sh"
    echo "Or download the whisper.cpp medium model manually into:"
    echo "  ${WHISPER_MODEL_PATH}"
  fi
fi

if ! cargo tauri --version >/dev/null 2>&1; then
  echo "Installing Tauri CLI v2 (first run may take several minutes)…"
  cargo install tauri-cli --locked --version "^2.0"
fi

echo ""
echo "Setup finished."
echo "Next:"
echo "  source ${ROOT}/.venv/bin/activate"
echo "  ollama pull qwen2.5:7b"
echo "  Microphone: macOS requires you to approve Terminal in System Settings → Privacy & Security → Microphone"
echo "  Run HER: cd ${ROOT}/src-tauri && cargo tauri dev"
