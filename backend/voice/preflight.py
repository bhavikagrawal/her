# Performs startup checks so the UI can give helpful, human-readable instructions.
# Whisper.cpp and microphone access are the two most common Phase 1 blockers on macOS.
# Instead of failing silently, we send one `error` event with exact commands/settings steps.
# This keeps the “presence” feeling: HER can still speak (TTS) even if STT is not ready yet.

"""Preflight checks for microphone + whisper.cpp availability (Phase 1)."""

from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd

from backend.voice.transcriber import resolve_whisper_binary, resolve_whisper_model


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    message: str


def check_whisper_ready() -> PreflightResult:
    """Return whether whisper binary + model file look present."""
    exe = resolve_whisper_binary()
    if exe is None:
        return PreflightResult(
            ok=False,
            message=(
                "Whisper not found (`whisper-cli`). Fix:\n"
                "  brew install whisper-cpp\n"
                "Then verify:\n"
                "  which whisper-cli\n"
                "Or set HER_WHISPER_BIN to the absolute path of your whisper binary."
            ),
        )
    model = resolve_whisper_model()
    if not model.is_file():
        return PreflightResult(
            ok=False,
            message=(
                "Whisper model missing (medium). Put it here:\n"
                f"  {model}\n"
                "See: data/models/whisper/README.txt"
            ),
        )
    return PreflightResult(ok=True, message="Whisper ready.")


def check_mic_ready() -> PreflightResult:
    """Return whether an input device exists and can be queried."""
    try:
        devices = sd.query_devices()
    except Exception as exc:
        return PreflightResult(
            ok=False,
            message=(
                "Microphone devices could not be queried. Fix:\n"
                "  System Settings → Privacy & Security → Microphone → enable Terminal\n"
                "Quick open (paste in Terminal):\n"
                "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone'\n"
                f"Details: {exc}"
            ),
        )

    has_input = any(int(d.get("max_input_channels", 0)) > 0 for d in devices)
    if not has_input:
        return PreflightResult(
            ok=False,
            message=(
                "No microphone input device detected. Fix:\n"
                "  Plug in / enable a mic, then re-run.\n"
                "Debug list (paste):\n"
                "  python3 -c \"import sounddevice as sd; print(sd.query_devices())\""
            ),
        )
    return PreflightResult(ok=True, message="Microphone detected.")

