# Will run Silero (or similar) in a side thread to watch for the user talking over HER.
# Voice activity detection is a polite doorbell: it tells the app when to yield the floor.
# Phase 0 has no audio, so this file is a named parking space for the interrupt pipeline.
# Isolating VAD keeps the main loop easier to read and to stop with shared events.

"""Voice activity detection placeholder for HER."""

from __future__ import annotations

__all__: list[str] = []
