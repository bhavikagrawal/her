# Turns assistant text into audio using Kokoro (English-only).
# This is HER’s vocal chords: every path must respect `stop_event` and interruption while playing.
# Phase 1 intentionally stays monolingual to reduce complexity and improve consistency.
# Missing model files raise clear errors so setup.sh / docs can point to the right commands.

"""Speech synthesis with Kokoro-ONNX (English-only)."""

from __future__ import annotations

import logging
import threading
import os
import time

import numpy as np
import sounddevice as sd
from backend.her_paths import kokoro_model_paths
from backend.voice.constants import SAMPLE_RATE

logger = logging.getLogger(__name__)

class Synthesizer:
    """Loads Kokoro once; speaks English text."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event
        self._output_device: int | None = None
        self._gain = float(os.environ.get("HER_TTS_GAIN", "2.35"))
        self._peak_target = float(os.environ.get("HER_TTS_PEAK", "0.92"))
        self._kokoro = None
        onnx_path, bin_path = kokoro_model_paths()
        if onnx_path.is_file() and bin_path.is_file():
            from kokoro_onnx import Kokoro as KokoroCls

            self._kokoro = KokoroCls(str(onnx_path), str(bin_path))
        else:
            logger.warning(
                "Kokoro models missing at %s / %s — speech output disabled until downloaded.",
                onnx_path,
                bin_path,
            )

    def set_output_device(self, device_id: int | None) -> None:
        """Select a PortAudio output device by numeric id (None = default OS device)."""
        self._output_device = device_id

    def set_tts_levels(self, *, gain: float | None = None, peak_target: float | None = None) -> None:
        """Update loudness controls live (no restart required)."""
        if gain is not None:
            self._gain = float(gain)
        if peak_target is not None:
            self._peak_target = float(peak_target)

    def synth_to_array(self, text: str) -> tuple[np.ndarray, int]:
        """Render `text` to mono float samples and sample rate."""
        stripped = text.strip()
        if not stripped:
            return np.zeros(0, dtype=np.float32), SAMPLE_RATE
        timing_enabled = bool(int(os.environ.get("HER_VOICE_TIMING_LOG", "0")))
        t0 = time.monotonic()
        samples, sr = self._kokoro_render(stripped)
        if timing_enabled:
            logger.info("voice_timing stage=tts_synth engine=kokoro ms=%.1f", (time.monotonic() - t0) * 1000.0)
        return samples, sr

    def _kokoro_render(self, text: str) -> tuple[np.ndarray, int]:
        """English Kokoro path."""
        if self._kokoro is None:
            raise RuntimeError("Kokoro weights are not installed — run scripts/download_voice_models.sh")
        last_err: Exception | None = None
        for voice in ("af_heart", "af_sarah"):
            try:
                samples, sample_rate = self._kokoro.create(
                    text,
                    voice=voice,
                    speed=0.92,
                    lang="en-us",
                )
                return np.asarray(samples, dtype=np.float32), int(sample_rate)
            except Exception as exc:
                last_err = exc
                continue
        raise RuntimeError(f"Kokoro synthesis failed: {last_err}") from last_err

    def _prepare_playback(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Peak-normalise (gain is applied dynamically during playback)."""
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return x
        peak = float(np.max(np.abs(x)))
        if peak > 1e-9:
            x = x * (self._peak_target / peak)
        # CONCEPT: float32 samples must stay in [-1, 1] for PortAudio; clipping avoids crackle from NaNs/inf.
        return x.astype(np.float32, copy=False)

    def play(
        self,
        samples: np.ndarray,
        sample_rate: int,
        interrupt_event: threading.Event,
        speaking_event: threading.Event,
    ) -> None:
        """Play through one continuous output stream (avoids click/static between chunk restarts)."""
        timing_enabled = bool(int(os.environ.get("HER_VOICE_TIMING_LOG", "0")))
        t0 = time.monotonic()
        prepared = self._prepare_playback(samples, sample_rate)
        if prepared.size == 0:
            return
        speaking_event.set()
        block = max(int(sample_rate * 0.04), 256)
        try:
            with sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                latency="low",
                device=self._output_device,
            ) as stream:
                offset = 0
                while offset < len(prepared):
                    if self._stop_event.is_set() or interrupt_event.is_set():
                        break
                    end = min(offset + block, len(prepared))
                    # Apply gain dynamically so volume changes take effect immediately mid-playback.
                    g = float(self._gain)
                    chunk = np.ascontiguousarray(np.clip(prepared[offset:end] * g, -1.0, 1.0).astype(np.float32, copy=False))
                    stream.write(chunk)
                    offset = end
                    # Yield occasionally so barge-in stays responsive without huge blocks.
                    time.sleep(0)
        finally:
            speaking_event.clear()
            if timing_enabled:
                logger.info("voice_timing stage=tts_play ms=%.1f", (time.monotonic() - t0) * 1000.0)
