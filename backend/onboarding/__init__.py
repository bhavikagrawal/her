# Handles first-run detection and greeting scripts once HER knows your name and tone.
# Onboarding is its own mini story arc with fades and audio transitions in the UI layer.
# Phase 0 ships only empty seats at this table; the front end later swaps screens here.
# Splitting onboarding keeps first-run logic out of unrelated networking code.

"""Onboarding flow subpackage for HER."""

from __future__ import annotations

__all__: list[str] = []
