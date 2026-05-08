# Turns a free-text city into country/region/confidence using local Ollama — like asking a well-read friend where Springfield might be.
# JSON-only prompts keep parsing predictable; regex extraction survives occasional markdown fences from the model.
# stop_event checks honor shutdown/barge-in so onboarding never blocks teardown mid-request.
# Offline-only: no geolocation APIs — aligns with HER privacy rules until decision.py approves network calls.

"""Offline city → region/country resolution via qwen2.5:7b (no network beyond localhost Ollama)."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
from typing import Any

from backend.ollama_client import DEFAULT_MODEL, collect_full_reply
from backend.onboarding.profile import LocationGuess

logger = logging.getLogger(__name__)

_JSON_OBJECT = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse first JSON object from model output; tolerate extra prose or fences."""
    text = (text or "").strip()
    if not text:
        return None
    for candidate in _JSON_OBJECT.findall(text):
        with contextlib.suppress(json.JSONDecodeError):
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
    with contextlib.suppress(json.JSONDecodeError):
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    return None


def resolve_city(city: str, stop_event: threading.Event | None) -> LocationGuess:
    """
    Ask the local LLM for a structured guess: country, region, confident.

    If parsing fails or Ollama is down, returns confident=False with empty strings.
    """
    halt = stop_event

    def aborted() -> bool:
        return halt is not None and halt.is_set()

    cleaned = (city or "").strip()
    if not cleaned:
        return LocationGuess(country="", region="", confident=False)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You map city names to geographic regions. Reply with ONLY a compact JSON object, "
                'no markdown, no explanation. Schema: {"country":"<English country name>",'
                '"region":"<state/province/region or empty string>",'
                '"confident": true|false}. '
                "Set confident=false when the city name is ambiguous (multiple cities share the name) "
                "or you are unsure."
            ),
        },
        {
            "role": "user",
            "content": f'City name: "{cleaned}"',
        },
    ]

    class _Stop:
        def is_set(self) -> bool:
            return aborted()

    try:
        raw = collect_full_reply(messages, _Stop(), model=DEFAULT_MODEL)
    except Exception as exc:
        logger.warning("resolve_city Ollama error: %s", exc)
        return LocationGuess(country="", region="", confident=False)

    if aborted():
        return LocationGuess(country="", region="", confident=False)

    obj = _extract_json_object(raw)
    if not obj:
        logger.debug("resolve_city could not parse JSON from: %s", raw[:200])
        return LocationGuess(country="", region="", confident=False)

    country = str(obj.get("country") or "").strip()
    region = str(obj.get("region") or "").strip()
    confident = bool(obj.get("confident", False))

    return LocationGuess(country=country, region=region, confident=confident)
