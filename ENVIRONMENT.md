# HER environment variables (deployment reference)
#
# This file is meant to be copy/pasteable: keep defaults, and only override what you need.
# CONCEPT: Environment variables let you change runtime behavior without editing code.
# Use `export VAR=value` in your shell, or set them in your process manager / Tauri launcher.

## Voice / STT / turn-taking

- **`HER_UTTERANCE_MERGE_WINDOW_S`** (default: `0.6`)
  - **What**: After the first utterance chunk ends, keep merging any follow-up chunks that arrive within this many seconds into the same turn (prevents answering mid-thought).
  - **Examples**:
    - `export HER_UTTERANCE_MERGE_WINDOW_S=0.6`
    - `export HER_UTTERANCE_MERGE_WINDOW_S=1.2`

- **`HER_MIC_INPUT_GAIN`** (default: `1.0`)
  - **What**: Digital gain applied to mic samples before VAD + WAV write.
  - **Example**: `export HER_MIC_INPUT_GAIN=2.0`

- **`HER_VAD_SPEECH_THRESHOLD`** (default: `0.55`)
  - **What**: Minimum Silero VAD speech probability to count as speech.
  - **Example**: `export HER_VAD_SPEECH_THRESHOLD=0.5`

- **`HER_VAD_SILENCE_CEIL`** (default: `0.30`)
  - **What**: Below this VAD probability we count frames as “quiet” for end-of-utterance.
  - **Example**: `export HER_VAD_SILENCE_CEIL=0.25`

- **`HER_SILENCE_FRAMES_END_UTTERANCE`** (default: `10`)
  - **What**: Quiet frames required to end an utterance. Lower = faster partial commits, but can split thoughts.
  - **Example**: `export HER_SILENCE_FRAMES_END_UTTERANCE=6`

## Barge-in (interrupting HER while she speaks)

- **`HER_BARGE_IN_FRAMES`** (default: `5`)
  - **What**: Consecutive qualifying frames required to trigger barge-in.
  - **Examples**:
    - `export HER_BARGE_IN_FRAMES=8`
    - `export HER_BARGE_IN_FRAMES=10`

- **`HER_BARGE_IN_GRACE_S`** (default: `0.35`)
  - **What**: Seconds after TTS starts during which barge-in is ignored (reduces speaker bleed false triggers).
  - **Example**: `export HER_BARGE_IN_GRACE_S=0.5`

- **`HER_BARGE_IN_VAD_THRESHOLD`** (default: `0.75`)
  - **What**: Minimum VAD probability required for barge-in (stricter than normal speech detection).
  - **Example**: `export HER_BARGE_IN_VAD_THRESHOLD=0.8`

- **`HER_BARGE_IN_MIN_DB`** (default: `-30.0`)
  - **What**: Minimum mic loudness (dBFS-ish) required for barge-in (filters low-level noise).
  - **Example**: `export HER_BARGE_IN_MIN_DB=-26`

## Whisper (STT engine)

- **`HER_WHISPER_BIN`** (default: unset)
  - **What**: Absolute path to `whisper-cli` / `main` (whisper.cpp) if it’s not on PATH.
  - **Example**: `export HER_WHISPER_BIN=/opt/homebrew/bin/whisper-cli`

- **`HER_WHISPER_MODEL`** (default: unset)
  - **What**: Absolute path to the whisper model file (ggml/gguf) instead of the default under `data/models/whisper/`.
  - **Example**: `export HER_WHISPER_MODEL="$PWD/data/models/whisper/ggml-small.bin"`

## STT language

- **`HER_STT_LANGUAGE`** (default: `auto`)
  - **What**: Language code passed to whisper.cpp (`-l`). `auto` lets Whisper detect each turn — recommended for HER's multilingual mirror behaviour.
  - **What gets parsed**: when `auto`, HER reads Whisper's `auto-detected language: xx (p = …)` line from stderr and routes the reply to a TTS voice in that language.
  - **Force a language**: pass an ISO 639-1 code (e.g. `en`, `hi`, `fr`) to lock detection — useful for noisy mics or running an offline test.
  - **Examples**:
    - `export HER_STT_LANGUAGE=auto`  *(default — multilingual)*
    - `export HER_STT_LANGUAGE=en`    *(force English)*

## Multilingual TTS

- HER speaks in the language Whisper hears (or, for typed input, what Lingua-py classifies). The router prefers Kokoro voices and falls back to macOS `say` when Kokoro doesn't ship a voice for that language.
- **Kokoro languages (full neural voices)**: English, Spanish, French, Italian, Portuguese, Hindi, Japanese, Mandarin Chinese.
- **macOS `say` fallback (always available on macOS)**: German, Russian, Korean, Arabic, Dutch, Turkish, Polish, Swedish (and any other language `say -v ?` supports — voices are mapped in `backend/voice/lang_routing.py`).
- **Failure mode**: if both Kokoro and `say` fail for a turn (e.g. unsupported language on a Linux build), HER emits a `tts` error event and stays silent for that sentence rather than crashing.
- **Adding a language**: add an entry to `PROFILES` in `backend/voice/lang_routing.py` with a Kokoro voice (when available) and the corresponding `say` voice name. Restart the backend.

## LLM (Ollama)

- **`HER_OLLAMA_MODEL`** (default: `qwen2.5:7b`)
  - **What**: Which Ollama chat model HER uses.
  - **Example**: `export HER_OLLAMA_MODEL=qwen2.5:7b`

- **`OLLAMA_HOST`** (default: `http://127.0.0.1:11434`)
  - **What**: Ollama base URL.
  - **Example**: `export OLLAMA_HOST=http://127.0.0.1:11434`

## TTS (Kokoro)

- **`HER_TTS_GAIN`** (default: `2.35`)
  - **What**: Post-normalization gain applied to TTS samples (too high can sound “static”/clipped).
  - **Example**: `export HER_TTS_GAIN=1.2`

- **`HER_TTS_PEAK`** (default: `0.92`)
  - **What**: Peak normalization target before gain/clipping.
  - **Example**: `export HER_TTS_PEAK=0.9`

## UI + debugging

- **`HER_TEXT_SYNC_WITH_VOICE`** (default: `1`)
  - **What**: When `1`, the UI text updates when a chunk is about to be spoken (in-sync). When `0`, it can “type ahead”.
  - **Example**: `export HER_TEXT_SYNC_WITH_VOICE=1`

- **`HER_MIC_METER`** (default: `1`)
  - **What**: When `1`, backend emits `mic_level` updates ~10×/sec for a live meter.
  - **Example**: `export HER_MIC_METER=1`

- **`HER_VOICE_TIMING_LOG`** (default: `0`)
  - **What**: Logs per-stage timing (wav write, whisper, TTS synth/play, barge-in triggers).
  - **Example**: `export HER_VOICE_TIMING_LOG=1`

- **`HER_CONVO_LOG`** (default: `0`)
  - **What**: Logs `heard_user ...` and `replied_assistant ...` lines (including the session opener).
  - **Example**: `export HER_CONVO_LOG=1`

## Data location

- **`HER_DATA_DIR`** (default: `<repo>/data`)
  - **What**: Override where HER stores models and temp audio.
  - **Example**: `export HER_DATA_DIR="$HOME/Library/Application Support/HER"`

## MemPalace (Phase 2 — long-term memory)

- **`HER_MEMPALACE_ENABLED`** (default: `1`)
  - **What**: When `0`, HER skips MemPalace reads/writes (Phase 1–style sessions).
  - **Example**: `export HER_MEMPALACE_ENABLED=0`

- **`HER_MEMPALACE_ROOT`** (default: unset → `<HER_DATA_DIR>/mempalace`)
  - **What**: Absolute path to the MemPalace palace directory (Chroma + `her_turns/` markdown sources).
  - **Example**: `export HER_MEMPALACE_ROOT="$HOME/Library/Application Support/HER/mempalace"`

- **`HER_MEMPALACE_WING`** (default: `her`)
  - **What**: MemPalace wing metadata for HER conversation drawers (search filter).
  - **Example**: `export HER_MEMPALACE_WING=her`

- **`HER_MEMPALACE_ROOM`** (default: `conversation`)
  - **What**: MemPalace room metadata for HER drawers.
  - **Example**: `export HER_MEMPALACE_ROOM=conversation`

- **`HER_MEMPALACE_CONTEXT_MAX_CHARS`** (default: `6000`)
  - **What**: Hard cap on the MemPalace block injected into the system prompt (wake-up + search hits).
  - **Example**: `export HER_MEMPALACE_CONTEXT_MAX_CHARS=4000`

- **`HER_MEMPALACE_SEARCH_TOP_K`** (default: `4`)
  - **What**: Number of semantic search results to include (1–20).
  - **Example**: `export HER_MEMPALACE_SEARCH_TOP_K=6`

**Embedding cache note:** Chroma’s default ONNX embedder downloads `all-MiniLM-L6-v2` under `~/.cache/chroma/onnx_models/` on first use (~300 MB). Ensure that path is writable, or pre-install offline.

**Audit / wipe:** Turn transcripts are also stored as files under `<palace>/her_turns/`. To delete all HER memory, quit the app and remove `HER_MEMPALACE_ROOT` (or `<data>/mempalace`). The WebSocket message `{"type":"memory_status"}` returns drawer counts and paths for inspection.

## Setup script helpers

- **`HER_FETCH_WHISPER_MODEL`** (default: `0`)
  - **What**: When `1`, `setup.sh` downloads the large Whisper medium model automatically.
  - **Example**: `HER_FETCH_WHISPER_MODEL=1 bash setup.sh`

---

## Suggested “deployment baseline” (copy/paste)

```bash
# Debug visibility (turn off in production)
export HER_VOICE_TIMING_LOG=0
export HER_CONVO_LOG=0

# UX defaults
export HER_TEXT_SYNC_WITH_VOICE=1
export HER_MIC_METER=1

# Mic sensitivity (tune per device)
export HER_MIC_INPUT_GAIN=2.0
export HER_VAD_SPEECH_THRESHOLD=0.55
export HER_VAD_SILENCE_CEIL=0.30
export HER_SILENCE_FRAMES_END_UTTERANCE=10

# Interrupt robustness
export HER_BARGE_IN_FRAMES=8
export HER_BARGE_IN_GRACE_S=0.5
export HER_BARGE_IN_VAD_THRESHOLD=0.8
export HER_BARGE_IN_MIN_DB=-26

# STT language (multilingual — Whisper auto-detects each turn)
export HER_STT_LANGUAGE=auto
```

