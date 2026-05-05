# Streams tokens from a local Ollama `/api/chat` session without uploading audio or disk snapshots.
# Streaming lets HER speak sentence-by-sentence while text still flows to the glass pane UI.
# Phase 1 pins `qwen2.5:7b`; swapping models later only touches env vars — not the UI protocol.
# HTTP stays on localhost; nothing here touches the public internet by default.

"""Minimal synchronous client for Ollama chat streaming."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, Protocol

import httpx

DEFAULT_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("HER_OLLAMA_MODEL", "qwen2.5:7b")


class _Cancellable(Protocol):
    """Minimal stop handle: `threading.Event` and our tiny `_CombinedStop` both satisfy this."""

    def is_set(self) -> bool: ...


def stream_chat(
    messages: list[dict[str, Any]],
    stop_event: _Cancellable,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE,
) -> Iterator[str]:
    """
    Yield assistant text **deltas** (new characters) until the stream completes or `stop_event`.

    Ollama’s streaming API returns the full `message.content` so far in each JSON line; we
    diff against the previous string to recover the fresh tail (the “delta” the UI needs).
    """
    payload = {"model": model, "messages": messages, "stream": True}
    previous: str = ""
    with httpx.Client(timeout=httpx.Timeout(600.0, read=600.0)) as client:
        with client.stream("POST", f"{base_url.rstrip('/')}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event.is_set():
                    break
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    break
                msg = data.get("message") or {}
                current: str = msg.get("content") or ""
                if not current:
                    continue
                if current.startswith(previous):
                    delta = current[len(previous) :]
                    previous = current
                    if delta:
                        yield delta
                else:
                    # Defensive: treat the whole piece as a delta if the model restarts content.
                    previous = current
                    yield current


def collect_full_reply(
    messages: list[dict[str, Any]],
    stop_event: _Cancellable,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE,
) -> str:
    """Concatenate deltas into one assistant string (history persistence)."""
    parts: list[str] = []
    for delta in stream_chat(
        messages, stop_event, model=model, base_url=base_url
    ):
        parts.append(delta)
    return "".join(parts)
