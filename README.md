# HER

HER is a **local, privacy-first** desktop companion for Apple Silicon Macs. **Phase 1** adds the full **voice loop**: microphone → Whisper.cpp → **Ollama (`qwen2.5:7b`)** → **Kokoro** → speakers, with **Silero VAD** for talk/end-of-turn + barge-in.

## Requirements

- macOS with **Apple Silicon**
- **Homebrew** (`https://brew.sh`)
- **Xcode Command Line Tools** (`xcode-select --install`)
- **Python 3.12+** (installed by `setup.sh` if missing)
- **Ollama** with `qwen2.5:7b` pulled locally
- **whisper.cpp** binary on `PATH` (Homebrew `whisper-cpp` or build from source) + **medium** weights in `data/models/whisper/ggml-medium.bin` (see `data/models/whisper/README.txt`)
- (English-only build) Speech output uses Kokoro’s English voice path.

## Quick start

```bash
cd /path/to/her
bash setup.sh
# Optional but recommended for first run (downloads ~1.5GB whisper medium weights):
# HER_FETCH_WHISPER_MODEL=1 bash setup.sh
source .venv/bin/activate
ollama pull qwen2.5:7b
cd src-tauri && cargo tauri dev
```

You should see `Python WebSocket server started on ws://localhost:8765`, then **listening…** when the voice thread arms. Speak a sentence: your words appear on the right, HER on the left, waveform animates while she speaks.

## Repository layout

- `backend/` — WebSocket + `VoiceSession` (mic, VAD, Whisper, Ollama stream, TTS)
- `frontend/` — Chat transcript + connection pill + waveform
- `src-tauri/` — Rust/Tauri shell
- `scripts/` — `run-backend.sh`, `download_voice_models.sh`, `generate_tauri_icon.py`
- `data/models/` — Downloaded weights (gitignored large binaries recommended)

## Troubleshooting

**`ModuleNotFoundError: No module named 'backend'`**

Running `python backend/main.py` puts only the `backend/` folder on `sys.path`. Either run through **`bash scripts/run-backend.sh`** (which sets `PYTHONPATH` to the repo root), or:

```bash
cd /path/to/her
export PYTHONPATH="$(pwd)"
python3 backend/main.py
```

**Tauri: `failed to open icon ... src-tauri/icons/icon.png`**

Run `python3 scripts/generate_tauri_icon.py` from the repo root, or `bash setup.sh` (it creates the placeholder if missing). The file must be **8-bit RGBA** (Tauri rejects plain RGB). Replace later with `cargo tauri icon path/to/your.png`.

**`beforeDevCommand`: `scripts/run-backend.sh` not found**

Tauri runs dev hooks from the **app root** (the folder that contains `src-tauri/`), not from inside `src-tauri/`. The config uses `bash scripts/run-backend.sh` so the path matches that layout.

**Port `8765` busy**

```bash
lsof -i :8765 | grep LISTEN
kill <PID>
```

**Microphone denied**

System Settings → Privacy & Security → Microphone → enable for **Terminal** (or the app bundle once packaged).

**`whisper.cpp binary not found`**

Install a build and ensure `whisper-cli` (or `main`) is on `PATH`, or set `HER_WHISPER_BIN` to the absolute path of the binary.

**Mic detected / device list**

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

**Open the Mic permission screen**

```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone'
```

**Kokoro model missing**

Re-run `bash scripts/download_voice_models.sh` (also invoked from `setup.sh`).

**TTS too quiet / scratchy chunks**

Audio is peak-normalised and amplified by default. Tune without code edits:

```bash
export HER_TTS_GAIN=3.0
```

Optional ceiling before clipping: `HER_TTS_PEAK=0.85`. Restart the backend after changing env vars.

## License

Private project — add a license before publishing.
