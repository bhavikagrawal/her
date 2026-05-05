# Orchestrates Phase 1: microphone chunks → Silero gate → Whisper → Qwen → Kokoro playback.
# Runs in a dedicated worker thread so asyncio WebSockets stay responsive while audio blocks.
# Two threading.Events enforce the workspace vows: global halt plus user “barge-in” during playback.
# State machines stay explicit because voice UX bugs usually trace to sloppy phase mixing.

"""Voice conversation loop used while the desktop WebSocket session is alive."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue
import tempfile
import threading
import time
import os
import math
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
import soundfile as sf
from silero_vad_lite import SileroVAD
from websockets.legacy.server import WebSocketServerProtocol

from backend.her_paths import temp_audio_dir
from backend.ollama_client import DEFAULT_MODEL, stream_chat
from backend.voice.constants import (
    BARGE_IN_SPEECH_FRAMES,
    BLOCK_SIZE,
    MIN_UTTERANCE_SAMPLES,
    SAMPLE_RATE,
    SILENCE_FRAMES_TO_END_UTTERANCE,
    VAD_SILENCE_CEIL,
    VAD_SPEECH_THRESHOLD,
)
from backend.voice.preflight import check_mic_ready, check_whisper_ready
from backend.voice.synthesizer import Synthesizer
from backend.voice.transcriber import transcribe_file

logger = logging.getLogger(__name__)


class _CombinedStop:
    """Tiny helper so Whisper/LLM loops stop when either shutdown or a per-turn barge-in fires."""

    __slots__ = ("_a", "_b")

    def __init__(self, a: threading.Event, b: threading.Event) -> None:
        self._a = a
        self._b = b

    def is_set(self) -> bool:
        return self._a.is_set() or self._b.is_set()


SYSTEM_PROMPT = (
    "You are HER — a warm, curious, attentive companion speaking to someone named User. "
    "This build is English-only: ask the user to speak English and respond in natural spoken English. "
    "Keep replies concise for voice (usually under four short sentences)."
)


def looks_non_english(text: str) -> bool:
    """
    Language guard: return True when text looks non-English.

    CONCEPT: Whisper is forced to English, but non-English utterances can still appear
    (as transliterated Latin words, or with non-ASCII characters).
    We use `langdetect` when available (offline, lightweight), and fall back to heuristics.
    """
    cleaned = text.strip()
    if not cleaned:
        return False

    # Fast path: any non-ASCII letters strongly suggests non-English (or names with accents).
    # This is intentionally strict to keep the build English-only.
    if any(ord(ch) > 127 for ch in cleaned):
        return True

    # Prefer a real language detector when installed.
    try:
        # langdetect is pure-Python and runs offline.
        from langdetect import detect  # type: ignore

        lang = detect(cleaned)
        return lang != "en"
    except Exception:
        pass

    lowered = cleaned.casefold()
    tokens = [t.strip(".,!?;:\"'()[]{}") for t in lowered.split()]
    # Minimal non-English “tell” list: catches many Hinglish/Hindi and common Romance particles.
    non_en_common = {
        # Hinglish/Hindi
        "haan",
        "han",
        "nahi",
        "nahin",
        "kya",
        "kyu",
        "kyun",
        "kaise",
        "kaisa",
        "kaisi",
        "kaun",
        "mera",
        "meri",
        "mere",
        "aap",
        "tum",
        "hai",
        "hain",
        # Spanish/French/Portuguese frequent words
        "que",
        "porque",
        "para",
        "pero",
        "hola",
        "gracias",
        "bonjour",
        "merci",
        "ça",
        "cest",
        "por",
    }
    hits = sum(1 for t in tokens if t in non_en_common)
    if hits >= 1:
        return True

    # Heuristic: if too few tokens look like English words (letters only), block.
    alpha_tokens = [t for t in tokens if t.isalpha()]
    if len(alpha_tokens) >= 3:
        # Very rough: English tends to have many short function words; non-English transliterations can skew.
        englishish = sum(1 for t in alpha_tokens if 2 <= len(t) <= 12)
        if englishish / len(alpha_tokens) < 0.6:
            return True
    return False


def drain_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split fully punctuated sentences; leave an unfinished tail for streaming continuation."""
    text = buffer.strip()
    if not text:
        return [], ""
    sentences: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        cut = -1
        idx = start
        while idx < length:
            ch = text[idx]
            if ch in ".?!…":
                nxt = idx + 1
                if nxt < length and text[nxt] in "\"'”’":
                    nxt += 1
                if nxt >= length or text[nxt].isspace():
                    cut = nxt
                    break
            idx += 1
        if cut == -1:
            break
        piece = text[start:cut].strip()
        if piece:
            sentences.append(piece)
        start = cut
        while start < length and text[start].isspace():
            start += 1
    remainder = text[start:]
    return sentences, remainder


class VoiceSession:
    """Blocking loop: capture speech, ask the LLM, stream UI text, speak audio with barge-in."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connection: WebSocketServerProtocol,
        halt: threading.Event,
        user_label: str = "User",
    ) -> None:
        self._loop = loop
        self._connection = connection
        self._halt = halt
        self._user_label = user_label
        self._messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT.replace("User", user_label)},
        ]
        self._interrupt = threading.Event()
        self._turn_stop: threading.Event = threading.Event()
        self._barge_frames = 0
        self._phase = "listen"
        self._last_speak_start = 0.0
        self._control_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._text_queue: queue.Queue[str] = queue.Queue()
        self._restart_stream = threading.Event()
        self._input_device: int | None = None
        self._output_device: int | None = None
        self._settings: dict[str, Any] = self._default_settings()
        self._settings_lock = threading.Lock()
        # CONCEPT: UI interactions (especially changing settings) can create tiny microphone spikes
        # (clicks, focus sounds, device reconfig) that look like "speech" and trigger barge-in.
        # We track recent settings activity and ignore barge-in for a short cooldown window.
        self._last_settings_change = 0.0

    def enqueue_control(self, payload: dict[str, Any]) -> None:
        """Receive UI control messages from the asyncio WebSocket thread."""
        # Apply settings immediately when possible so changes don't have to wait for the voice thread
        # to return from Whisper / LLM / TTS playback.
        if payload.get("type") == "set_settings":
            updates = payload.get("values")
            if isinstance(updates, dict):
                with self._settings_lock:
                    self._settings.update(updates)
        try:
            self._control_queue.put_nowait(payload)
        except queue.Full:
            logger.warning("control queue full; dropping message: %s", payload.get("type"))

    def _default_settings(self) -> dict[str, Any]:
        """Build runtime settings (defaults can be overridden by env or UI)."""
        def f(name: str, default: float) -> float:
            return float(os.environ.get(name, str(default)))

        def i(name: str, default: int) -> int:
            return int(os.environ.get(name, str(default)))

        def b(name: str, default: int) -> bool:
            return bool(int(os.environ.get(name, str(default))))

        return {
            # Input / VAD
            "mic_input_gain": f("HER_MIC_INPUT_GAIN", 1.0),
            "mic_muted": b("HER_MIC_MUTED", 0),
            "vad_speech_threshold": f("HER_VAD_SPEECH_THRESHOLD", 0.55),
            "vad_silence_ceil": f("HER_VAD_SILENCE_CEIL", 0.30),
            "silence_frames_end_utterance": i("HER_SILENCE_FRAMES_END_UTTERANCE", 10),
            "utterance_merge_window_s": f("HER_UTTERANCE_MERGE_WINDOW_S", 0.6),
            # Barge-in
            "barge_in_frames": i("HER_BARGE_IN_FRAMES", 5),
            "barge_in_grace_s": f("HER_BARGE_IN_GRACE_S", 0.35),
            "barge_in_vad_threshold": f("HER_BARGE_IN_VAD_THRESHOLD", 0.75),
            "barge_in_min_db": f("HER_BARGE_IN_MIN_DB", -30.0),
            # TTS loudness
            "tts_gain": f("HER_TTS_GAIN", 2.35),
            "tts_peak": f("HER_TTS_PEAK", 0.92),
            "tts_muted": b("HER_TTS_MUTED", 0),
            # UX/debug
            "mic_meter": b("HER_MIC_METER", 1),
            "voice_timing_log": b("HER_VOICE_TIMING_LOG", 0),
            "convo_log": b("HER_CONVO_LOG", 0),
            # STT
            "stt_language": str(os.environ.get("HER_STT_LANGUAGE", "en")).strip() or "en",
        }

    def _emit_settings_schema(self) -> None:
        """Send settings metadata so UI can render sliders/toggles."""
        schema: list[dict[str, Any]] = [
            {
                "key": "mic_input_gain",
                "label": "Mic sensitivity",
                "kind": "range",
                "min": 0.5,
                "max": 4.0,
                "step": 0.1,
                "help": "Digital gain applied to your microphone before speech detection and transcription.",
            },
            {
                "key": "utterance_merge_window_s",
                "label": "Wait for full thought",
                "kind": "range",
                "min": 0.0,
                "max": 2.0,
                "step": 0.05,
                "help": "Merges short pauses into one turn so HER doesn't answer mid-sentence. Higher waits longer.",
            },
            {
                "key": "silence_frames_end_utterance",
                "label": "End-of-speech delay",
                "kind": "range",
                "min": 3,
                "max": 25,
                "step": 1,
                "help": "How much silence ends your turn. Lower is faster; higher reduces accidental cutoffs.",
            },
            {
                "key": "vad_speech_threshold",
                "label": "Speech detection strictness",
                "kind": "range",
                "min": 0.35,
                "max": 0.85,
                "step": 0.01,
                "help": "Lower hears quieter speech but may pick up more noise.",
            },
            {
                "key": "barge_in_frames",
                "label": "Interrupt sensitivity",
                "kind": "range",
                "min": 3,
                "max": 20,
                "step": 1,
                "help": "How much confirmed speech is required to interrupt HER while she is speaking. Higher = fewer false interrupts.",
            },
            {
                "key": "barge_in_grace_s",
                "label": "Interrupt grace period",
                "kind": "range",
                "min": 0.0,
                "max": 1.2,
                "step": 0.05,
                "help": "Ignores interrupts briefly after HER starts speaking (prevents speaker bleed false triggers).",
            },
            {
                "key": "tts_gain",
                "label": "Voice volume",
                "kind": "range",
                "min": 0.6,
                "max": 3.5,
                "step": 0.05,
                "help": "Amplifies HER's voice after peak-normalization. Too high can sound clipped/static.",
            },
            {
                "key": "tts_muted",
                "label": "Mute HER",
                "kind": "toggle",
                "help": "Silences HER's voice output (text still streams).",
            },
            {
                "key": "mic_meter",
                "label": "Show mic meter",
                "kind": "toggle",
                "help": "Shows a small mic activity meter while listening.",
            },
        ]
        self._emit({"type": "settings_schema", "schema": schema, "values": self._settings})

    def _emit_audio_devices(self) -> None:
        """Send PortAudio device lists so the UI can offer a picker when multiple exist."""
        try:
            devices = sd.query_devices()
            default_in, default_out = sd.default.device
        except Exception as exc:
            self._emit(
                {
                    "type": "error",
                    "stage": "audio_devices",
                    "message": f"Could not query audio devices: {exc}",
                }
            )
            return

        def _safe_int(x: Any) -> int | None:
            try:
                val = int(x)
            except Exception:
                return None
            return val if val >= 0 else None

        default_in_id = _safe_int(default_in)
        default_out_id = _safe_int(default_out)

        inputs: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        for idx, d in enumerate(devices):
            name = str(d.get("name") or f"Device {idx}")
            max_in = int(d.get("max_input_channels", 0) or 0)
            max_out = int(d.get("max_output_channels", 0) or 0)
            if max_in > 0:
                inputs.append({"id": idx, "name": name, "default": default_in_id is not None and idx == default_in_id})
            if max_out > 0:
                outputs.append({"id": idx, "name": name, "default": default_out_id is not None and idx == default_out_id})

        self._emit(
            {
                "type": "audio_devices",
                "inputs": inputs,
                "outputs": outputs,
                "selected_input": self._input_device,
                "selected_output": self._output_device,
            }
        )

    async def _send_raw(self, line: str) -> None:
        await self._connection.send(line)

    def _emit(self, payload: dict[str, Any]) -> None:
        """Ship JSON to the WebView on the asyncio thread."""
        line = json.dumps(payload)
        fut = asyncio.run_coroutine_threadsafe(self._send_raw(line), self._loop)
        try:
            fut.result(timeout=30.0)
        except Exception as exc:  # pragma: no cover - network specific
            logger.warning("failed to emit event: %s", exc)

    def run(self) -> None:
        """Entry point for `threading.Thread`; returns when `halt` is set or stream errors."""
        utterance_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=4)
        vad = SileroVAD(SAMPLE_RATE)
        synth = Synthesizer(self._halt)
        # Live-updated settings (may be changed from UI).
        timing_enabled = bool(self._settings.get("voice_timing_log", False))
        meter_enabled = bool(self._settings.get("mic_meter", True))
        meter_rms: float = 0.0
        meter_last_emit = 0.0
        mic_gain = float(self._settings.get("mic_input_gain", 1.0))
        mic_muted = bool(self._settings.get("mic_muted", False))
        # Barge-in tuning: reduce false interrupts from noise / speaker bleed.
        barge_grace_s = float(self._settings.get("barge_in_grace_s", 0.35))
        barge_prob = float(self._settings.get("barge_in_vad_threshold", 0.75))
        barge_db = float(self._settings.get("barge_in_min_db", -30.0))
        barge_frames_required = int(self._settings.get("barge_in_frames", 5))
        vad_speech_threshold = float(self._settings.get("vad_speech_threshold", 0.55))
        vad_silence_ceil = float(self._settings.get("vad_silence_ceil", 0.30))
        silence_frames_end = int(self._settings.get("silence_frames_end_utterance", 10))
        merge_window_s = float(self._settings.get("utterance_merge_window_s", 0.6))
        stt_language = str(self._settings.get("stt_language", "en"))
        synth.set_tts_levels(gain=float(self._settings.get("tts_gain", 2.35)), peak_target=float(self._settings.get("tts_peak", 0.92)))

        opener_spoken = False
        state: dict[str, Any] = {
            "recording": False,
            "chunks": [],
            "silence_run": 0,
            "speech_frames": 0,
        }

        self._emit_audio_devices()
        self._emit_settings_schema()

        def drain_utterances() -> int:
            """Drop any queued audio chunks (prevents stale turns after restarts)."""
            dropped = 0
            while True:
                try:
                    utterance_queue.get_nowait()
                except queue.Empty:
                    return dropped
                else:
                    dropped += 1

        def drain_controls() -> None:
            while True:
                try:
                    msg = self._control_queue.get_nowait()
                except queue.Empty:
                    return
                msg_type = msg.get("type")
                if msg_type == "user_text":
                    raw = msg.get("text")
                    if isinstance(raw, str):
                        text = raw.strip()
                        if text:
                            # Typed messages should interrupt HER immediately (same as barge-in).
                            self._interrupt.set()
                            self._turn_stop.set()
                            try:
                                self._text_queue.put_nowait(text)
                            except queue.Full:
                                # Drop oldest typed message if the user spams Enter.
                                with contextlib.suppress(queue.Empty):
                                    _ = self._text_queue.get_nowait()
                                self._text_queue.put_nowait(text)
                    continue
                if msg_type == "set_audio_devices":
                    in_id = msg.get("input_id")
                    out_id = msg.get("output_id")
                    new_in = int(in_id) if isinstance(in_id, int) else None
                    new_out = int(out_id) if isinstance(out_id, int) else None
                    in_changed = new_in != self._input_device
                    out_changed = new_out != self._output_device
                    # CONCEPT: Only restart the mic when the INPUT actually changed.
                    # Otherwise we loop: frontend "restores" selection on every audio_devices
                    # broadcast, we restart the stream, which re-broadcasts, which restores… etc.
                    if in_changed:
                        self._input_device = new_in
                        self._restart_stream.set()
                    if out_changed:
                        self._output_device = new_out
                        synth.set_output_device(self._output_device)
                    if in_changed or out_changed:
                        self._emit_audio_devices()
                    continue
                if msg_type == "set_settings":
                    updates = msg.get("values")
                    if isinstance(updates, dict):
                        self._settings.update(updates)
                        self._last_settings_change = time.monotonic()
                        # Refresh live variables (used by callback/main loop).
                        nonlocal timing_enabled, meter_enabled, mic_gain
                        nonlocal mic_muted
                        nonlocal barge_grace_s, barge_prob, barge_db, barge_frames_required
                        nonlocal vad_speech_threshold, vad_silence_ceil, silence_frames_end
                        nonlocal merge_window_s, stt_language
                        timing_enabled = bool(self._settings.get("voice_timing_log", False))
                        meter_enabled = bool(self._settings.get("mic_meter", True))
                        mic_gain = float(self._settings.get("mic_input_gain", 1.0))
                        mic_muted = bool(self._settings.get("mic_muted", False))
                        barge_grace_s = float(self._settings.get("barge_in_grace_s", 0.35))
                        barge_prob = float(self._settings.get("barge_in_vad_threshold", 0.75))
                        barge_db = float(self._settings.get("barge_in_min_db", -30.0))
                        barge_frames_required = int(self._settings.get("barge_in_frames", 5))
                        vad_speech_threshold = float(self._settings.get("vad_speech_threshold", 0.55))
                        vad_silence_ceil = float(self._settings.get("vad_silence_ceil", 0.30))
                        silence_frames_end = int(self._settings.get("silence_frames_end_utterance", 10))
                        merge_window_s = float(self._settings.get("utterance_merge_window_s", 0.6))
                        stt_language = str(self._settings.get("stt_language", "en"))
                        synth.set_tts_levels(
                            gain=float(self._settings.get("tts_gain", 2.35)),
                            peak_target=float(self._settings.get("tts_peak", 0.92)),
                        )
                        self._emit_settings_schema()
                    continue

        def audio_callback(indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
            if status:
                logger.debug("PortAudio status: %s", status)
            if self._halt.is_set():
                raise sd.CallbackStop
            if mic_muted:
                # Mute input: don't run VAD, don't record, keep UI alive.
                state["recording"] = False
                state["chunks"] = []
                state["silence_run"] = 0
                state["speech_frames"] = 0
                return
            mono = indata[:, 0].astype(np.float32, copy=False)
            block = mono.astype(np.float32, copy=True)
            if mic_gain != 1.0:
                # CONCEPT: Digital gain helps when the OS input level is low.
                # Clamp to avoid numeric blowups; downstream WAV write uses PCM_16.
                block = np.clip(block * mic_gain, -1.0, 1.0).astype(np.float32, copy=False)
            prob = vad.process(block.tobytes())
            # Always compute RMS cheaply (used by both the mic meter and barge-in loudness gate).
            rms_local = float(np.sqrt(np.mean(np.square(block), dtype=np.float64)))
            if meter_enabled:
                # CONCEPT: RMS is a simple “loudness” proxy for a VU meter.
                # Keep it ultra-light: no websocket calls from the audio callback.
                nonlocal meter_rms
                meter_rms = rms_local

            if self._phase == "speak":
                # Ignore barge-in briefly after any settings update (prevents accidental cutoffs
                # when the user tweaks sliders/toggles while HER is mid-sentence).
                if (time.monotonic() - self._last_settings_change) < 0.80:
                    self._barge_frames = 0
                    return
                # Ignore potential barge-in for a short grace window after playback starts.
                if barge_grace_s > 0 and (time.monotonic() - self._last_speak_start) < barge_grace_s:
                    self._barge_frames = 0
                    return
                if prob >= barge_prob:
                    # Require "more confident than normal" VAD + a minimum energy floor.
                    db = 20.0 * math.log10(max(rms_local, 1e-9))
                    if db < barge_db:
                        self._barge_frames = 0
                        return
                    self._barge_frames += 1
                    if self._barge_frames >= barge_frames_required:
                        if timing_enabled:
                            logger.info(
                                "voice_timing stage=barge_in_triggered frames=%d prob=%.3f",
                                int(self._barge_frames),
                                float(prob),
                            )
                        self._interrupt.set()
                        self._turn_stop.set()
                else:
                    self._barge_frames = 0
                return

            speech = prob >= vad_speech_threshold
            quiet = prob < vad_silence_ceil
            if not state["recording"]:
                if speech:
                    state["speech_frames"] += 1
                    if state["speech_frames"] >= 2:
                        state["recording"] = True
                        state["chunks"] = [block.copy()]
                        state["silence_run"] = 0
                else:
                    state["speech_frames"] = 0
                return

            state["chunks"].append(block.copy())
            if speech:
                state["silence_run"] = 0
            elif quiet:
                state["silence_run"] += 1
                if state["silence_run"] >= silence_frames_end:
                    audio = np.concatenate(state["chunks"]) if state["chunks"] else block
                    drop = silence_frames_end * BLOCK_SIZE
                    if len(audio) > drop:
                        audio = audio[:-drop]
                    state["recording"] = False
                    state["chunks"] = []
                    state["silence_run"] = 0
                    state["speech_frames"] = 0
                    if len(audio) >= MIN_UTTERANCE_SAMPLES:
                        try:
                            utterance_queue.put_nowait(audio)
                        except queue.Full:
                            logger.warning("utterance queue saturated — dropping oldest")
                            try:
                                utterance_queue.get_nowait()
                            except queue.Empty:
                                pass
                            utterance_queue.put_nowait(audio)

        mic_result = check_mic_ready()
        whisper_result = check_whisper_ready()
        if not mic_result.ok:
            self._emit({"type": "error", "stage": "mic", "message": mic_result.message})
        if not whisper_result.ok:
            self._emit({"type": "error", "stage": "whisper", "message": whisper_result.message})

        if not mic_result.ok:
            # Without a mic, we can’t run the live loop; keep the socket alive so the user sees guidance.
            while not self._halt.is_set():
                drain_controls()
                self._halt.wait(0.25)
            return
        logger.info("mic_preflight ok; entering capture loop")

        while not self._halt.is_set():
            drain_controls()
            try_devices: list[int | None] = [self._input_device]
            if self._input_device is None:
                # Heuristic: when AirPods are the OS default mic, PortAudio can fail at 16 kHz.
                # Prefer the built-in MacBook mic if it exists.
                with contextlib.suppress(Exception):
                    devices = sd.query_devices()
                    for idx, d in enumerate(devices):
                        name = str(d.get("name") or "")
                        max_in = int(d.get("max_input_channels", 0) or 0)
                        if max_in <= 0:
                            continue
                        if "MacBook" in name and "Microphone" in name:
                            try_devices.append(idx)
                            break

            last_exc: Exception | None = None
            stream: sd.InputStream | None = None
            chosen_device: int | None = None
            for dev in try_devices:
                try:
                    stream = sd.InputStream(
                        channels=1,
                        samplerate=SAMPLE_RATE,
                        blocksize=BLOCK_SIZE,
                        dtype="float32",
                        callback=audio_callback,
                        device=dev,
                    )
                    chosen_device = dev
                    last_exc = None
                    logger.info("mic_open ok device=%s sr=%s block=%s", chosen_device, SAMPLE_RATE, BLOCK_SIZE)
                    break
                except Exception as exc:
                    last_exc = exc
                    continue

            if stream is None:
                self._emit(
                    {
                        "type": "error",
                        "stage": "mic",
                        "message": f"Could not open microphone input at {SAMPLE_RATE} Hz. "
                        f"Selected device={self._input_device}. Error: {last_exc}",
                    }
                )
                self._halt.wait(0.35)
                continue

            if chosen_device != self._input_device:
                # We fell back automatically; reflect the actual device in state/UI.
                self._input_device = chosen_device
                self._emit_audio_devices()

            self._restart_stream.clear()
            if timing_enabled:
                dropped = drain_utterances()
                if dropped:
                    logger.info("voice_timing stage=utterance_flush count=%d", dropped)
            state["recording"] = False
            state["chunks"] = []
            state["silence_run"] = 0
            state["speech_frames"] = 0

            try:
                with stream:
                    self._emit({"type": "voice_ready"})
                    if not opener_spoken:
                        # HER speaks first on session start (Phase 1: no memory yet, just warmth + presence).
                        # CONCEPT: We generate an opener via the same local LLM stream we use for replies,
                        # then speak it sentence-by-sentence so the UI and audio stay in sync.
                        with contextlib.suppress(Exception):
                            self._speak_session_opener(synth)
                        opener_spoken = True
                    while not self._halt.is_set():
                        drain_controls()
                        if self._restart_stream.is_set():
                            if timing_enabled:
                                dropped = drain_utterances()
                                if dropped:
                                    logger.info("voice_timing stage=utterance_flush count=%d", dropped)
                            break
                        if meter_enabled and self._phase == "listen":
                            now = time.monotonic()
                            if now - meter_last_emit >= 0.10:
                                meter_last_emit = now
                                db = 20.0 * math.log10(max(meter_rms, 1e-9))
                                self._emit({"type": "mic_level", "rms": meter_rms, "db": db})
                        try:
                            # Typed chat gets priority over audio so the “chat bar” feels instant.
                            typed = self._text_queue.get_nowait()
                        except queue.Empty:
                            typed = None
                        if typed is not None:
                            self._handle_typed_text(typed, synth)
                            continue
                        try:
                            audio = utterance_queue.get(timeout=0.12)
                        except queue.Empty:
                            continue
                        # Merge back-to-back utterances so slow/pausy speakers aren't split into
                        # multiple "turns" that get answered one by one.
                        merged = [audio]
                        merge_deadline = time.monotonic() + max(0.0, merge_window_s)
                        while time.monotonic() < merge_deadline and not self._restart_stream.is_set() and not self._halt.is_set():
                            try:
                                nxt = utterance_queue.get_nowait()
                            except queue.Empty:
                                # No chunk ready right now; wait a tiny bit (no busy spin).
                                time.sleep(0.02)
                                continue
                            else:
                                merged.append(nxt)
                                merge_deadline = time.monotonic() + max(0.0, merge_window_s)
                        if len(merged) > 1:
                            # Insert a short padding gap so Whisper doesn't smash words together.
                            gap = np.zeros(int(SAMPLE_RATE * 0.08), dtype=np.float32)
                            audio = np.concatenate([p for pair in zip(merged, [gap] * len(merged)) for p in pair])[:-len(gap)]
                            if timing_enabled:
                                logger.info("voice_timing stage=utterance_merged parts=%d samples=%d", len(merged), int(audio.shape[0]))
                        if timing_enabled:
                            logger.info(
                                "voice_timing stage=utterance_dequeued samples=%d ms=0.0",
                                int(audio.shape[0]),
                            )
                        self._handle_utterance(audio, synth)
            except Exception as exc:
                logger.exception("mic_stream crashed")
                self._emit({"type": "error", "stage": "mic_stream", "message": str(exc)})
                self._halt.wait(0.35)
                continue

    def _handle_typed_text(self, text: str, synth: Synthesizer) -> None:
        """Handle a typed chat message (no STT)."""
        cleaned = text.strip()
        if not cleaned:
            return
        if looks_non_english(cleaned):
            self._emit(
                {
                    "type": "error",
                    "stage": "language",
                    "message": "English-only mode: please type that in English.",
                }
            )
            return
        convo_log = bool(self._settings.get("convo_log", False))
        self._turn_stop = threading.Event()
        self._interrupt.clear()
        if convo_log:
            logger.info("typed_user %s", cleaned.replace("\n", " ").strip())
        self._emit({"type": "user_transcript", "text": cleaned})
        self._messages.append({"role": "user", "content": cleaned})
        self._emit({"type": "assistant_reset"})
        try:
            self._emit({"type": "status_text", "text": "thinking…"})
            self._stream_reply(synth)
        finally:
            self._emit({"type": "status_text", "text": "listening…"})

    def _handle_utterance(self, audio: np.ndarray, synth: Synthesizer) -> None:
        """Transcribe, stream LLM text, speak sentence-sized audio segments."""
        self._turn_stop = threading.Event()
        self._interrupt.clear()
        timing_enabled = bool(self._settings.get("voice_timing_log", False))
        convo_log = bool(self._settings.get("convo_log", False))
        t_dequeue = time.monotonic()
        self._emit({"type": "status_text", "text": "transcribing…"})
        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            dir=temp_audio_dir(),
            delete=False,
        ) as tmp:
            wav_path = Path(tmp.name)
        t_wav0 = time.monotonic()
        sf.write(str(wav_path), audio, SAMPLE_RATE, subtype="PCM_16")
        t_wav1 = time.monotonic()
        if timing_enabled:
            logger.info(
                "voice_timing stage=wav_written ms=%.1f file=%s",
                (t_wav1 - t_wav0) * 1000.0,
                wav_path.name,
            )
        try:
            t_wh0 = time.monotonic()
            text = transcribe_file(wav_path, self._halt, language=str(self._settings.get("stt_language", "en")))
            t_wh1 = time.monotonic()
            if timing_enabled:
                logger.info(
                    "voice_timing stage=whisper_done ms=%.1f ms_since_dequeue=%.1f",
                    (t_wh1 - t_wh0) * 1000.0,
                    (t_wh1 - t_dequeue) * 1000.0,
                )
        except Exception as exc:
            self._emit({"type": "error", "stage": "whisper", "message": str(exc)})
            return
        finally:
            wav_path.unlink(missing_ok=True)

        cleaned = text.strip()
        if not cleaned:
            self._emit({"type": "status_text", "text": "listening…"})
            return
        if looks_non_english(cleaned):
            self._emit(
                {
                    "type": "error",
                    "stage": "language",
                    "message": "English-only mode: please repeat that in English.",
                }
            )
            self._emit({"type": "status_text", "text": "listening…"})
            return
        if convo_log:
            logger.info("heard_user %s", cleaned.replace("\n", " ").strip())
        self._emit({"type": "user_transcript", "text": cleaned})
        self._messages.append({"role": "user", "content": cleaned})
        self._emit({"type": "assistant_reset"})
        try:
            if timing_enabled:
                logger.info(
                    "voice_timing stage=llm_start ms_since_dequeue=%.1f",
                    (time.monotonic() - t_dequeue) * 1000.0,
                )
            self._emit({"type": "status_text", "text": "thinking…"})
            self._stream_reply(synth)
        except Exception as exc:
            logger.exception("assistant pipeline failed")
            self._emit({"type": "error", "stage": "llm", "message": str(exc)})
        finally:
            self._emit({"type": "status_text", "text": "listening…"})

    def _speak_session_opener(self, synth: Synthesizer) -> None:
        """Generate + speak a short opener as soon as the app connects."""
        self._turn_stop = threading.Event()
        self._interrupt.clear()
        self._emit({"type": "assistant_reset"})
        convo_log = bool(self._settings.get("convo_log", False))
        opener_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.replace("User", self._user_label)
                + " Speak first when the session begins.",
            },
            {
                "role": "user",
                "content": (
                    f"Generate a warm, natural session opener for {self._user_label}. "
                    "2 sentences maximum. Never start with 'Hello' or 'Hi'. "
                    "Start with their name or an observation. "
                    "Do not mention AI, models, assistants, or systems."
                ),
            },
        ]
        trimmed = self._stream_text_and_speak(opener_messages, synth)
        if trimmed:
            if convo_log:
                logger.info("replied_assistant %s", trimmed.replace("\n", " ").strip())
            self._messages.append({"role": "assistant", "content": trimmed})

    def _stream_text_and_speak(self, messages: list[dict[str, Any]], synth: Synthesizer) -> str:
        """
        Keep the LLM stream moving while TTS plays queued sentence chunks.

        CONCEPT: This is a producer/consumer pattern. The producer thread keeps reading
        model tokens and queueing complete sentences; the voice thread consumes that queue
        for playback so audio does not pause the text stream.
        """
        full_parts: list[str] = []
        sentence_queue: queue.Queue[str | None] = queue.Queue()
        error_queue: queue.Queue[Exception] = queue.Queue(maxsize=1)
        combo = _CombinedStop(self._halt, self._turn_stop)

        def produce_sentences() -> None:
            tts_tail = ""
            try:
                for delta in stream_chat(messages, combo, model=DEFAULT_MODEL):
                    full_parts.append(delta)
                    # Stream exactly what the LLM is producing so the UI looks like one continuous message.
                    self._emit({"type": "assistant_delta", "text": delta})
                    if self._turn_stop.is_set():
                        break
                    tts_tail += delta
                    sentences, tts_tail = drain_complete_sentences(tts_tail)
                    for sentence in sentences:
                        if self._turn_stop.is_set():
                            break
                        sentence_queue.put(sentence)
                if not self._turn_stop.is_set():
                    tail = tts_tail.strip()
                    if tail:
                        sentence_queue.put(tail)
            except Exception as exc:
                with contextlib.suppress(queue.Full):
                    error_queue.put_nowait(exc)
            finally:
                sentence_queue.put(None)

        producer = threading.Thread(target=produce_sentences, name="her-llm-stream", daemon=True)
        producer.start()
        while not self._halt.is_set():
            if self._turn_stop.is_set():
                break
            try:
                sentence = sentence_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if sentence is None:
                break
            self._synthesize_sentence(sentence, synth)

        if self._turn_stop.is_set() or self._halt.is_set():
            producer.join(timeout=2.0)
        else:
            producer.join()
        try:
            raise error_queue.get_nowait()
        except queue.Empty:
            pass
        return "".join(full_parts).strip()

    def _stream_reply(self, synth: Synthesizer) -> None:
        """Stream token deltas to the UI while speaking completed sentences aloud."""
        convo_log = bool(self._settings.get("convo_log", False))
        trimmed = self._stream_text_and_speak(self._messages, synth)
        if trimmed:
            if convo_log:
                logger.info("replied_assistant %s", trimmed.replace("\n", " ").strip())
            self._messages.append({"role": "assistant", "content": trimmed})

    def _synthesize_sentence(self, sentence: str, synth: Synthesizer) -> None:
        """Synthesize one chunk; respects barge-in and global shutdown flags."""
        if self._turn_stop.is_set():
            return
        # Refresh per-sentence TTS levels so UI volume changes take effect mid-reply.
        with self._settings_lock:
            gain = float(self._settings.get("tts_gain", 2.35))
            peak = float(self._settings.get("tts_peak", 0.92))
            muted = bool(self._settings.get("tts_muted", False))
        synth.set_tts_levels(gain=gain, peak_target=peak)
        if muted:
            return
        self._interrupt.clear()
        self._barge_frames = 0
        self._phase = "speak"
        # Timestamp used by the mic callback to apply a short barge-in grace window.
        self._last_speak_start = time.monotonic()
        speaking = threading.Event()
        self._emit({"type": "her_speaking", "active": True})
        try:
            samples, sr = synth.synth_to_array(sentence)
            if samples.size == 0:
                return
            synth.play(samples, sr, self._interrupt, speaking)
        except Exception as exc:
            logger.exception("TTS failure")
            self._emit({"type": "error", "stage": "tts", "message": str(exc)})
        finally:
            self._phase = "listen"
            self._emit({"type": "her_speaking", "active": False})

    def run_settings_only(self) -> None:
        """
        Settings-only WebSocket session: no mic, no STT, no TTS.

        CONCEPT: The Settings window is a separate WebView that connects to the same backend.
        If we open the microphone for *every* connection, the settings window can contend with
        the main voice session and make listening appear "broken".
        """
        self._emit_audio_devices()
        self._emit_settings_schema()
        while not self._halt.is_set():
            try:
                msg = self._control_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            msg_type = msg.get("type")
            if msg_type == "set_audio_devices":
                in_id = msg.get("input_id")
                out_id = msg.get("output_id")
                self._input_device = int(in_id) if isinstance(in_id, int) else None
                self._output_device = int(out_id) if isinstance(out_id, int) else None
                self._emit_audio_devices()
                continue

            if msg_type == "set_settings":
                updates = msg.get("values")
                if isinstance(updates, dict):
                    with self._settings_lock:
                        self._settings.update(updates)
                    self._emit_settings_schema()
                continue
