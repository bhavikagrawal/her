# Numbers that keep the microphone, Silero chunk size, and VAD threshold in agreement.
# 16 kHz × 32 ms = 512 samples — exactly what `silero-vad-lite` expects per `process()` call.
# Threshold 0.6 matches the product spec: decisive enough to ignore noise, not so high it misses soft speech.
# Silence frame counts convert human “brief pause” into machine-friendly end-of-utterance detection.

"""Audio/VAD tuning constants shared by HER’s Phase 1 voice pipeline."""

from __future__ import annotations

import os

# Hardware-style sample clock: matches Silero lite 16 kHz constraint.
SAMPLE_RATE: int = 16000
# One VAD quantum: 512 samples ≈ 32 ms at 16 kHz (see silero-vad-lite README).
BLOCK_SIZE: int = 512
# Spec: Silero speech probability must exceed this to count as “you are talking”.
# Lowering this helps quiet speakers; keep it env-tunable to avoid regressions in noisy rooms.
VAD_SPEECH_THRESHOLD: float = float(os.environ.get("HER_VAD_SPEECH_THRESHOLD", "0.55"))
# Frames below this probability count as “quiet” while deciding utterance endpoints.
VAD_SILENCE_CEIL: float = float(os.environ.get("HER_VAD_SILENCE_CEIL", "0.30"))
# ~12 frames × 32 ms ≈ 384 ms of quiet ends a user turn (tunable feel of “done talking”).
# Allow tuning by env so slow speakers can be handled without code edits.
SILENCE_FRAMES_TO_END_UTTERANCE: int = int(os.environ.get("HER_SILENCE_FRAMES_END_UTTERANCE", "10"))
# Ignore extremely short blips from desk bumps or fans.
MIN_UTTERANCE_SAMPLES: int = 2400  # 150 ms
# Consecutive high-probability frames required to trigger barge-in while HER speaks.
# CONCEPT: “Barge-in” means we stop HER’s playback when *you* start speaking.
# We require multiple consecutive VAD-positive frames so tiny noises don’t instantly cut her off.
# 5 frames × 32 ms ≈ 160 ms — still feels immediate, but filters coughs/clicks better.
BARGE_IN_SPEECH_FRAMES: int = int(os.environ.get("HER_BARGE_IN_FRAMES", "5"))
