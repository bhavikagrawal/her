# Bridges HER's voice loop to MemPalace: verbatim turn files, Chroma retrieval, wake-up context.
# MemPalace owns embeddings and search; HER only chooses when to read/write and prompt budgets.
# Stop events short-circuit slow paths so shutdown and barge-in never wait on vector search.
# Palace path and wing/room stay env-tunable so packaging can relocate storage without code edits.

"""MemPalace integration: ingest conversation turns and retrieve context for the LLM."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any

from backend.her_paths import mempalace_dir, mempalace_identity_path, mempalace_turns_dir

logger = logging.getLogger(__name__)

_WING_DEFAULT = "her"
_ROOM_DEFAULT = "conversation"
_AGENT_NAME = "her-voice"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def palace_path_str() -> str:
    """Resolved absolute path to the on-disk MemPalace root."""
    override = os.environ.get("HER_MEMPALACE_ROOT", "").strip()
    if override:
        p = os.path.abspath(os.path.expanduser(override))
        os.makedirs(p, exist_ok=True)
        return p
    return str(mempalace_dir())


def mempalace_enabled() -> bool:
    """When False, skip all MemPalace I/O (Phase 1 behavior)."""
    return _env_bool("HER_MEMPALACE_ENABLED", True)


def wing_name() -> str:
    return os.environ.get("HER_MEMPALACE_WING", _WING_DEFAULT).strip() or _WING_DEFAULT


def room_name() -> str:
    return os.environ.get("HER_MEMPALACE_ROOM", _ROOM_DEFAULT).strip() or _ROOM_DEFAULT


def context_char_budget() -> int:
    return max(500, _env_int("HER_MEMPALACE_CONTEXT_MAX_CHARS", 6000))


def search_top_k() -> int:
    return max(1, min(20, _env_int("HER_MEMPALACE_SEARCH_TOP_K", 4)))


def _check(stop: threading.Event | None) -> bool:
    return stop is not None and stop.is_set()


def ensure_mempalace_collections(palace_path: str) -> None:
    """Create empty Chroma collections if missing so wake-up/search work before first turn."""
    from mempalace.palace import get_closets_collection, get_collection

    get_collection(palace_path, create=True)
    get_closets_collection(palace_path, create=True)


class HerMemPalace:
    """One palace per process; safe to share across VoiceSession instances."""

    def __init__(self, stop_event: threading.Event | None = None) -> None:
        self._stop = stop_event
        self._palace_path = palace_path_str()
        self._identity_path = str(mempalace_identity_path())
        self._wing = wing_name()
        self._room = room_name()
        self._turn_dir = mempalace_turns_dir()
        self._collection = None
        if mempalace_enabled():
            try:
                ensure_mempalace_collections(self._palace_path)
                self._get_collection()
            except Exception as exc:  # noqa: BLE001
                logger.warning("MemPalace could not open/create collections: %s", exc)

    def _get_collection(self):  # type: ignore[no-untyped-def]
        if self._collection is not None:
            return self._collection
        from mempalace.palace import get_collection

        self._collection = get_collection(self._palace_path, create=True)
        return self._collection

    def record_turn(
        self,
        session_key: str,
        turn_index: int,
        user_text: str,
        assistant_text: str,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Persist one exchange as a markdown file and a MemPalace drawer."""
        if not mempalace_enabled():
            return
        halt = stop_event or self._stop
        if _check(halt):
            return
        now = datetime.now().astimezone()
        date_str = now.date().isoformat()
        dow = now.strftime("%A")
        body = (
            f"Recorded_at: {now.isoformat()}\n"
            f"Recorded_date: {date_str}\n"
            f"Recorded_weekday: {dow}\n\n"
            f"### User\n{user_text.strip()}\n\n### Assistant\n{assistant_text.strip()}\n"
        )
        if len(body) < 12:
            return
        path = self._turn_dir / f"{session_key}_{turn_index:06d}.md"
        try:
            path.write_text(body, encoding="utf-8")
        except OSError as exc:
            logger.warning("mempalace turn file write failed: %s", exc)
            return
        if _check(halt):
            return
        try:
            from mempalace.miner import add_drawer

            add_drawer(
                self._get_collection(),
                self._wing,
                self._room,
                body,
                str(path.resolve()),
                0,
                _AGENT_NAME,
            )
        except Exception as exc:  # noqa: BLE001 — MemPalace/Chroma errors are user-environment specific
            logger.warning("mempalace add_drawer failed: %s", exc)

    def context_for_query(
        self,
        query: str,
        user_label: str,
        stop_event: threading.Event | None = None,
    ) -> str:
        """Return a bounded text block: wake-up stack plus semantic hits for this query."""
        if not mempalace_enabled():
            return ""
        halt = stop_event or self._stop
        if _check(halt):
            return ""
        query = query.strip()
        if not query:
            return ""
        # Expand relative date words so semantic search can match stored ISO dates.
        # MemPalace retrieves text; it doesn't do calendaring on its own.
        now = datetime.now().astimezone()
        today = now.date()
        yesterday = today - timedelta(days=1)
        q_lower = query.casefold()
        if "yesterday" in q_lower:
            query = f"{query} (yesterday was {yesterday.isoformat()})"
        if "today" in q_lower:
            query = f"{query} (today is {today.isoformat()})"
        budget = context_char_budget()
        parts: list[str] = []
        try:
            from mempalace.layers import MemoryStack

            stack = MemoryStack(palace_path=self._palace_path, identity_path=self._identity_path)
            if _check(halt):
                return ""
            wake = stack.wake_up(wing=self._wing)
            if wake.strip():
                label = f"(Speaking with {user_label}. Use memory only when relevant; do not invent facts.)\n\n"
                chunk = label + wake.strip()
                parts.append(chunk[: min(3500, budget)])
        except Exception as exc:  # noqa: BLE001
            logger.debug("mempalace wake_up skipped: %s", exc)
        if _check(halt):
            return ""
        try:
            from mempalace.searcher import search_memories

            res = search_memories(
                query,
                self._palace_path,
                wing=self._wing,
                room=self._room,
                n_results=search_top_k(),
            )
            if isinstance(res, dict) and res.get("error"):
                logger.debug("mempalace search: %s", res.get("error"))
            else:
                hits = res.get("results") if isinstance(res, dict) else None
                if hits:
                    lines: list[str] = ["### Relevant past turns (semantic search)"]
                    for i, hit in enumerate(hits, start=1):
                        if _check(halt):
                            break
                        text = (hit.get("text") or "").strip()
                        if not text:
                            continue
                        lines.append(f"[{i}] {text[:1200]}")
                    block = "\n\n".join(lines)
                    parts.append(block)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mempalace search_memories failed: %s", exc)
        out = "\n\n".join(p for p in parts if p).strip()
        if len(out) > budget:
            out = out[:budget] + "\n…"
        return out


def status_dict() -> dict[str, Any]:
    """JSON-serializable snapshot for WebSocket `memory_status` and debugging."""
    if not mempalace_enabled():
        return {
            "enabled": False,
            "palace_path": palace_path_str(),
            "message": "MemPalace disabled (HER_MEMPALACE_ENABLED=0).",
        }
    path = palace_path_str()
    out: dict[str, Any] = {
        "enabled": True,
        "palace_path": path,
        "wing": wing_name(),
        "room": room_name(),
        "identity_path": str(mempalace_identity_path()),
        "turns_dir": str(mempalace_turns_dir()),
    }
    try:
        ensure_mempalace_collections(path)
        from mempalace.layers import MemoryStack

        stack = MemoryStack(palace_path=path, identity_path=str(mempalace_identity_path()))
        out["memory_stack"] = stack.status()
    except Exception as exc:  # noqa: BLE001
        out["memory_stack_error"] = str(exc)
    return out
