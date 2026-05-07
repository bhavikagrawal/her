# Turns assistant text into audio via Kokoro (English + 7 langs) with a macOS `say` fallback.
# This is HER's vocal chords: every path must respect `stop_event` and interruption while playing.
# Phase 1.5 added multilingual routing: if Kokoro can't speak the chosen language we shell out to
# the Apple `say` binary (always-on macOS, no extra installs) so HER never goes silent.

"""Speech synthesis with Kokoro-ONNX + macOS `say` fallback (multilingual)."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from backend.her_paths import kokoro_model_paths, temp_audio_dir
from backend.voice.constants import SAMPLE_RATE
from backend.voice.lang_routing import (
    DEFAULT_LANG,
    LangProfile,
    has_macos_say,
    profile_for,
)

logger = logging.getLogger(__name__)


class Synthesizer:
    """Loads Kokoro once; speaks text in the requested language (Kokoro → say fallback)."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event
        self._output_device: int | None = None
        self._gain = float(os.environ.get("HER_TTS_GAIN", "2.35"))
        self._peak_target = float(os.environ.get("HER_TTS_PEAK", "0.92"))
        self._kokoro = None
        # Cache which Kokoro voices/langs we've already proven work on this build of the
        # voice file — Kokoro raises if a voice isn't bundled (see `voices-v1.0.bin`).
        self._kokoro_blacklist: set[str] = set()
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

    def synth_to_array(
        self,
        text: str,
        lang_code: str = DEFAULT_LANG,
    ) -> tuple[np.ndarray, int]:
        """Render `text` (in `lang_code`, ISO 639-1) to mono float samples + sample rate.

        Routing order:
          1. Kokoro in the requested language (when a voice + espeak code are mapped).
          2. Kokoro in English (so we never go silent on a Kokoro-supported language file).
          3. macOS `say` in the closest available voice.
        """
        stripped = text.strip()
        if not stripped:
            return np.zeros(0, dtype=np.float32), SAMPLE_RATE
        timing_enabled = bool(int(os.environ.get("HER_VOICE_TIMING_LOG", "0")))
        t0 = time.monotonic()
        profile = profile_for(lang_code)

        engine = "kokoro"
        try:
            samples, sr = self._render(stripped, profile)
        except Exception as exc:
            logger.warning("Primary TTS path failed for lang=%s: %s — trying fallback.", profile.code, exc)
            samples, sr = self._render_say(stripped, profile)
            engine = "say"

        if timing_enabled:
            logger.info(
                "voice_timing stage=tts_synth engine=%s lang=%s ms=%.1f",
                engine,
                profile.code,
                (time.monotonic() - t0) * 1000.0,
            )
        return samples, sr

    def _render(self, text: str, profile: LangProfile) -> tuple[np.ndarray, int]:
        """Pick Kokoro when the language is supported, else hop straight to `say`."""
        if self._kokoro is not None and profile.kokoro_voice and profile.kokoro_lang:
            cache_key = f"{profile.kokoro_voice}@{profile.kokoro_lang}"
            if cache_key not in self._kokoro_blacklist:
                try:
                    return self._kokoro_render(text, profile)
                except Exception as exc:
                    self._kokoro_blacklist.add(cache_key)
                    logger.warning(
                        "Kokoro path %s failed (%s); falling back to `say` for future calls.",
                        cache_key,
                        exc,
                    )
        # Fallback: macOS `say` in the requested language.
        return self._render_say(text, profile)

    def _kokoro_render(self, text: str, profile: LangProfile) -> tuple[np.ndarray, int]:
        """Synthesize with Kokoro using the voice/lang from `profile`."""
        if self._kokoro is None:
            raise RuntimeError("Kokoro weights are not installed — run scripts/download_voice_models.sh")
        last_err: Exception | None = None
        # Try the language-specific voice first; for English we keep the historical
        # multi-voice fallback (af_heart → af_sarah) for resilience against bad weights.
        candidates: list[str] = [profile.kokoro_voice or "af_heart"]
        if profile.code == DEFAULT_LANG:
            candidates.append("af_sarah")
        kokoro_lang = profile.kokoro_lang or "en-us"
        for voice in candidates:
            try:
                samples, sample_rate = self._kokoro.create(
                    text,
                    voice=voice,
                    speed=0.92,
                    lang=kokoro_lang,
                )
                return np.asarray(samples, dtype=np.float32), int(sample_rate)
            except Exception as exc:
                last_err = exc
                continue
        raise RuntimeError(f"Kokoro synthesis failed (lang={profile.code}): {last_err}") from last_err

    def _render_say(self, text: str, profile: LangProfile) -> tuple[np.ndarray, int]:
        """Use the macOS `say` binary to render `text` (catches every Kokoro gap)."""
        if not has_macos_say():
            raise RuntimeError(
                f"No TTS engine could speak language={profile.code}: Kokoro lacks a voice "
                f"and macOS `say` is not available on this system."
            )
        # Some installs of `say` are picky about voice names per region; if the chosen voice
        # is not present we fall back to the system default voice (still the right language
        # most of the time on macOS Sonoma+).
        out_path = Path(tempfile.mkstemp(suffix=".aiff", dir=str(temp_audio_dir()))[1])
        cmd = ["say"]
        if profile.say_voice:
            cmd += ["-v", profile.say_voice]
        cmd += ["-o", str(out_path), text]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=60.0,
            )
            if completed.returncode != 0 and profile.say_voice:
                # Voice not installed — retry with the system default voice.
                err = completed.stderr.decode("utf-8", errors="replace").strip()
                logger.info("say voice=%s failed (%s); retrying with default voice.", profile.say_voice, err)
                completed = subprocess.run(
                    ["say", "-o", str(out_path), text],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=60.0,
                )
            if completed.returncode != 0:
                err = completed.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"`say` failed ({completed.returncode}): {err}")
            data, sr = sf.read(str(out_path), dtype="float32", always_2d=False)
            if data.ndim == 2:
                # `say` is mono in practice but be defensive against stereo AIFFs.
                data = data.mean(axis=1).astype(np.float32, copy=False)
            return np.asarray(data, dtype=np.float32), int(sr)
        finally:
            out_path.unlink(missing_ok=True)

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
                    g = float(self._gain)
                    chunk = np.ascontiguousarray(np.clip(prepared[offset:end] * g, -1.0, 1.0).astype(np.float32, copy=False))
                    stream.write(chunk)
                    offset = end
                    time.sleep(0)
        finally:
            speaking_event.clear()
            if timing_enabled:
                logger.info("voice_timing stage=tts_play ms=%.1f", (time.monotonic() - t0) * 1000.0)
