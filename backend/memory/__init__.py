# Co-locates ChromaDB soft memory and SQLite state for facts, settings, and safety logs.
# Two stores are like quick notes on a desk (Chroma) and a locked filing cabinet (SQLite).
# Phase 0 does not open either store; the app only checks the WebSocket control channel.
# Defining the package now keeps import paths stable for the rest of the repository.

"""Memory and structured state subpackage for HER."""

from __future__ import annotations

__all__: list[str] = []
