# Handles first-run detection, JSON profile persistence, and first-greeting prompt assembly.
# Splitting onboarding keeps SQLite-free profile storage and greeting prompts out of the voice loop file.
# Phase 3 wires WebSocket `onboarding_complete` into `VoiceSession` so greeting audio shares the normal TTS path.
# Downstream phases can swap `profile.json` for multi-user storage without renaming these imports.

"""Onboarding flow: profile JSON, city resolution, first-greeting messages."""

from __future__ import annotations

from backend.onboarding.greeting import first_greeting_messages
from backend.onboarding.location import resolve_city
from backend.onboarding.profile import (
    Profile,
    is_first_launch,
    load_profile,
    profile_from_onboarding_values,
    profile_path,
    save_profile,
)

__all__: list[str] = [
    "Profile",
    "first_greeting_messages",
    "is_first_launch",
    "load_profile",
    "profile_from_onboarding_values",
    "profile_path",
    "resolve_city",
    "save_profile",
]
