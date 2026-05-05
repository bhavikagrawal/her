# Hands recorded audio to whisper.cpp so YOUR words become UTF-8 text before the LLM sees them.
# Whisper runs as a subprocess — easier to swap Metal-enabled builds without recompiling HER.
# Phase 1 (English-only): we pin `-l en` for faster + more consistent English transcripts.
# Long runs are capped with a timeout so a stuck whisper build cannot wedge the companion process.

"""whisper.cpp subprocess wrapper for local speech-to-text."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from backend.her_paths import temp_audio_dir, whisper_model_path

logger = logging.getLogger(__name__)


def resolve_whisper_binary() -> Path | None:
    """Locate a whisper.cpp `main`/`whisper-cli` binary from PATH or Homebrew layouts."""
    env_bin = os.environ.get("HER_WHISPER_BIN")
    if env_bin:
        p = Path(env_bin).expanduser()
        if p.is_file():
            return p
    for name in ("whisper-cli", "whisper", "main"):
        found = shutil.which(name)
        if found:
            return Path(found)
    brew = Path("/opt/homebrew/bin/whisper-cli")
    if brew.is_file():
        return brew
    intel_brew = Path("/usr/local/bin/whisper-cli")
    if intel_brew.is_file():
        return intel_brew
    return None


def resolve_whisper_model() -> Path:
    """Return ggml model path (defaults under `data/models/whisper/`)."""
    env_model = os.environ.get("HER_WHISPER_MODEL")
    if env_model:
        return Path(env_model).expanduser()
    return whisper_model_path()


def transcribe_file(
    wav_path: Path,
    stop_event: threading.Event,
    *,
    whisper_bin: Path | None = None,
    model_path: Path | None = None,
    language: str | None = None,
) -> str:
    """Run whisper.cpp on `wav_path` and return transcript text."""
    if stop_event.is_set():
        return ""
    timing_enabled = bool(int(os.environ.get("HER_VOICE_TIMING_LOG", "0")))
    t0 = time.monotonic()
    exe = whisper_bin or resolve_whisper_binary()
    if exe is None:
        raise RuntimeError(
            "whisper.cpp binary not found — install whisper-cpp or set HER_WHISPER_BIN."
        )
    model = model_path or resolve_whisper_model()
    if not model.is_file():
        raise RuntimeError(
            f"Whisper weights missing at {model} — download ggml-medium.bin into data/models/whisper/."
        )
    out_dir = Path(tempfile.mkdtemp(prefix="wh_spk_", dir=temp_audio_dir()))
    lang = (language or os.environ.get("HER_STT_LANGUAGE", "en")).strip() or "en"
    cmd = [
        str(exe),
        "-m",
        str(model.resolve()),
        "-f",
        str(wav_path.resolve()),
        "-l",
        lang,
        "-otxt",
        "-of",
        "utt",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            cwd=str(out_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=240.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("whisper.cpp timed out — model too heavy or audio corrupt.") from exc
    if stop_event.is_set():
        return ""
    if completed.returncode != 0:
        err = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"whisper failed ({completed.returncode}): {err}")
    if timing_enabled:
        logger.info("voice_timing stage=whisper_subprocess ms=%.1f", (time.monotonic() - t0) * 1000.0)
    candidates = sorted(out_dir.glob("*.txt"))
    if not candidates:
        logger.warning("whisper produced no txt under %s", out_dir)
        for path in out_dir.glob("*"):
            path.unlink(missing_ok=True)
        out_dir.rmdir()
        return ""
    text = candidates[0].read_text(encoding="utf-8", errors="replace").strip()
    for path in out_dir.glob("*"):
        path.unlink(missing_ok=True)
    out_dir.rmdir()
    return text
