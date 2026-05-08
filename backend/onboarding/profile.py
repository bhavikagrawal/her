# Persists one user's onboarding answers as JSON under HER_DATA_DIR for second-launch detection.
# Atomic replace avoids half-written files if the process dies mid-save — like finishing a sentence before hanging up.
# Single-file profile keeps Phase 3 simple; multi-user later can shard filenames or migrate to SQLite.
# pathlib.Path keeps paths portable when HER_DATA_DIR points at Application Support or another disk.

"""Load/save HER user profile (`data/profile.json`) for onboarding and personalization."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.her_paths import data_dir


@dataclass
class LocationGuess:
    """Offline LLM guess for where a city sits on Earth (country / region / confidence)."""

    country: str = ""
    region: str = ""
    confident: bool = False


@dataclass
class Profile:
    """Fields collected during onboarding + derived location metadata."""

    name: str = ""
    gender: str = ""
    city: str = ""
    preferred_language: str = ""
    preferred_language_code: str = ""
    location: LocationGuess | None = None
    setup_complete: bool = False
    created_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        """Safe subset for WebSocket payloads (no secrets — there are none yet)."""
        loc = self.location
        return {
            "name": self.name,
            "gender": self.gender,
            "city": self.city,
            "preferred_language": self.preferred_language,
            "preferred_language_code": self.preferred_language_code,
            "setup_complete": self.setup_complete,
            "location": None
            if loc is None
            else {"country": loc.country, "region": loc.region, "confident": loc.confident},
        }


def profile_path() -> Path:
    """Return absolute path to `profile.json` under the configured data directory."""
    return data_dir() / "profile.json"


def _parse_location(raw: Any) -> LocationGuess | None:
    """Turn JSON dict into LocationGuess; tolerate missing keys."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    return LocationGuess(
        country=str(raw.get("country") or "").strip(),
        region=str(raw.get("region") or "").strip(),
        confident=bool(raw.get("confident", False)),
    )


def load_profile() -> Profile | None:
    """Read profile from disk; return None if missing or unreadable."""
    path = profile_path()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    loc = _parse_location(data.get("location"))
    created = str(data.get("created_at") or "").strip()
    return Profile(
        name=str(data.get("name") or "").strip(),
        gender=str(data.get("gender") or "").strip(),
        city=str(data.get("city") or "").strip(),
        preferred_language=str(data.get("preferred_language") or "").strip(),
        preferred_language_code=str(data.get("preferred_language_code") or "").strip(),
        location=loc,
        setup_complete=bool(data.get("setup_complete", False)),
        created_at=created,
    )


def is_first_launch() -> bool:
    """True when no profile exists or onboarding never finished."""
    prof = load_profile()
    if prof is None:
        return True
    return not prof.setup_complete


def save_profile(profile: Profile) -> None:
    """Write profile atomically (temp file + replace)."""
    path = profile_path()
    tmp = path.with_suffix(".json.tmp")
    if not profile.created_at:
        profile.created_at = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "name": profile.name,
        "gender": profile.gender,
        "city": profile.city,
        "preferred_language": profile.preferred_language,
        "preferred_language_code": profile.preferred_language_code,
        "setup_complete": profile.setup_complete,
        "created_at": profile.created_at,
    }
    if profile.location is not None:
        payload["location"] = asdict(profile.location)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def profile_from_onboarding_values(values: dict[str, Any]) -> Profile:
    """Build profile from WebSocket `onboarding_complete`; language is always English at onboarding."""
    return Profile(
        name=str(values.get("name") or "").strip(),
        gender=str(values.get("gender") or "").strip(),
        city=str(values.get("city") or "").strip(),
        preferred_language="English",
        preferred_language_code="en",
        location=None,
        setup_complete=True,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
