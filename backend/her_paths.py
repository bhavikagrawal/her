# Resolves `data/` and model paths without hardcoding your username or machine-specific prefixes.
# Centralizing paths lets Whisper, Kokoro, and MemPalace agree on where artifacts live on disk.
# `HER_DATA_DIR` overrides the default so packaging can relocate storage later without code edits.
# Every helper returns pathlib.Path so downstream modules stay consistent with project rules.

"""Filesystem layout helpers for HER models and temporary audio."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root (directory above `backend/`)."""
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Return persisted data directory, creating it when missing."""
    raw = os.environ.get("HER_DATA_DIR")
    base = Path(raw).expanduser() if raw else project_root() / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    """Subfolder for all downloadable neural weights (Kokoro, Whisper)."""
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def kokoro_model_paths() -> tuple[Path, Path]:
    """Paths to Kokoro ONNX weights shipped separately from PyPI."""
    base = models_dir() / "kokoro"
    base.mkdir(parents=True, exist_ok=True)
    onnx = base / "kokoro-v1.0.onnx"
    voices = base / "voices-v1.0.bin"
    return onnx, voices


def whisper_model_path() -> Path:
    """Default ggml/gguf medium model for whisper.cpp."""
    return models_dir() / "whisper" / "ggml-medium.bin"


def temp_audio_dir() -> Path:
    """Short-lived WAV files for Whisper hand-off."""
    p = data_dir() / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mempalace_dir() -> Path:
    """Root directory for MemPalace Chroma palace files (Phase 2 long-term memory)."""
    p = data_dir() / "mempalace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mempalace_turns_dir() -> Path:
    """Per-turn markdown files fed to MemPalace as drawer sources (audit trail on disk)."""
    p = mempalace_dir() / "her_turns"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mempalace_identity_path() -> Path:
    """Layer-0 identity file MemPalace reads for wake-up context (short, user-editable)."""
    path = mempalace_dir() / "identity.txt"
    if not path.exists():
        path.write_text(
            "HER companion memory (MemPalace).\n"
            "Edit this file to pin stable facts you want always in wake-up context.\n",
            encoding="utf-8",
        )
    return path
