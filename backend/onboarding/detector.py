# Will read SQLite to learn whether setup finished before showing chat or forms again.
# Same idea as checking if you already introduced yourself at a friend's dinner party.
# Phase 0 never touches disk here; connection testing happens entirely over WebSockets.
# A dedicated detector avoids sprinkling boolean checks across unrelated UI controllers.

"""First-run / setup detection placeholder for HER."""

from __future__ import annotations

__all__: list[str] = []
