# Co-locates MemPalace long-term memory; structured onboarding profile lives in `data/profile.json` (Phase 3).
# MemPalace holds verbatim turns + Chroma retrieval; future phases may add more tables without tangling imports.
# The adapter stays thin so the voice loop does not import MemPalace internals directly.
# Defining the package now keeps import paths stable for the rest of the repository.

"""Memory and structured state subpackage for HER."""

from __future__ import annotations

__all__: list[str] = ["HerMemPalace", "status_dict"]

from backend.memory.mempalace_adapter import HerMemPalace, status_dict
