# Will own profile fields, online decision logs, and "which questions we already asked" records.
# SQLite is a small, reliable desk drawer: exact rows, easy backups, and local privacy by default.
# Phase 0 has no on-disk database file in the test path; this file is a future home for SQL.
# Centralized access keeps schema migrations from duplicating across the tree.

"""SQLite profile and app state placeholder for HER."""

from __future__ import annotations

__all__: list[str] = []
