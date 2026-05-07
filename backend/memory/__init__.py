# Co-locates MemPalace (Phase 2) and placeholders for future SQLite profile state.
# MemPalace holds verbatim turns + Chroma retrieval; profile DB arrives in later phases.
# The adapter stays thin so the voice loop does not import MemPalace internals directly.
# Defining the package now keeps import paths stable for the rest of the repository.

"""Memory and structured state subpackage for HER."""

from __future__ import annotations

__all__: list[str] = ["HerMemPalace", "status_dict"]

from backend.memory.mempalace_adapter import HerMemPalace, status_dict
