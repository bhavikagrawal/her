# Builds the two-message chat payload for HER's very first spoken greeting after onboarding completes.
# The system message pins English for onboarding completion; later turns still mirror Whisper/Lingua per Phase 1.5.
# User prompt forbids fake history (“we met before”) and gimmicky weather small-talk users find creepy.
# Scene: this is second zero of the relationship — HER only knows what the form just collected.

"""First-launch greeting prompt assembly for HER (post-onboarding, streaming + TTS)."""

from __future__ import annotations

from backend.onboarding.profile import Profile
from backend.voice.lang_routing import DEFAULT_LANG, detect_text_language, profile_for


def _resolve_lang_code(profile: Profile) -> str:
    """Prefer explicit onboarding ISO code; fall back to Lingua on the language label."""
    raw = (profile.preferred_language_code or "").strip().lower()
    if raw and len(raw) >= 2:
        base = raw.split("-")[0][:2]
        return profile_for(base).code
    hint = (profile.preferred_language or "").strip()
    if hint:
        return detect_text_language(hint)
    return DEFAULT_LANG


def _language_directive_from_profile(profile: Profile) -> str:
    """Tell the LLM which spoken language to use (matches TTS routing)."""
    code = _resolve_lang_code(profile)
    prof = profile_for(code)
    if prof.code == DEFAULT_LANG:
        return "Reply in natural spoken English."
    return (
        f"The user chose {prof.label} for your voice. Reply in fluent, natural {prof.label}. "
        "Do not switch away unless they do."
    )


def _profile_block(profile: Profile) -> str:
    """Human-readable facts for the system prompt."""
    lines = [
        "## User profile",
        f"- Name: {profile.name}",
        f"- Gender (for tone): {profile.gender}",
        f"- City they typed: {profile.city}",
        "- Preferred spoken language: English (default profile language).",
    ]
    if profile.preferred_language_code:
        lines.append(f"- Language ISO for TTS routing: {profile.preferred_language_code}")
    loc = profile.location
    if loc is not None:
        if loc.country or loc.region:
            lines.append(
                f"- Offline guess where that city is: {loc.region}, {loc.country} "
                f"(confident={loc.confident}). Never pretend you are physically there."
            )
        else:
            lines.append("- Offline location guess failed — do not invent geography.")
    return "\n".join(lines)


def first_greeting_messages(profile: Profile, base_system: str) -> list[dict[str, str]]:
    """
    Return `[system, user]` messages for streaming the first-ever greeting after onboarding.

    `base_system` is HER's core persona prompt (same as VoiceSession SYSTEM_PROMPT with name substituted).
    """
    directive = _language_directive_from_profile(profile)
    block = _profile_block(profile)
    loc = profile.location
    ambiguous = loc is not None and not loc.confident

    system_content = (
        f"{base_system}\n\n{block}\n\n## Language for this turn\n{directive}\n"
        "You are speaking aloud for the very first time with this person — "
        "only facts above exist; there is no shared past."
    )

    user_instructions = [
        f"Say your first greeting to {profile.name} now — this moment is when you meet them.",
        "Exactly 2 short sentences (spoken aloud).",
        f"Use their name once in the first sentence.",
        "Sound genuinely glad they're here; never imply you met before today or spent time together.",
        "Do not ask how the weather is where they are — it feels intrusive and you are not there.",
        "Do not say you are 'in' their city or 'with them' there — you only know the city name they typed.",
        "Never mention AI, assistants, models, chatbots, or systems.",
        "Do not start with 'Hello' or 'Hi'.",
    ]
    if ambiguous:
        user_instructions.append(
            "Their city name might be ambiguous worldwide — end with one brief clarifying question "
            "(two region options max)."
        )
    else:
        user_instructions.append(
            "You may lightly nod to the place they mentioned if confident; otherwise skip place entirely."
        )

    user_content = " ".join(user_instructions)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
