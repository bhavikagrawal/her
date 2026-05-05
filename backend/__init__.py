# Marks `backend` as a Python package so imports stay organized as HER grows.
# Empty packages still matter: later modules use `from backend.memory import …` cleanly.
# Phase 0 does not load these submodules yet; `main.py` runs as a script entrypoint.
# Keeping one package root avoids scattering Python files without a shared namespace.
"""HER Python backend package."""

from __future__ import annotations

__all__: list[str] = []
