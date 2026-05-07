# Decides which language code to use for STT, LLM, and TTS so HER mirrors the speaker.
# Uses Whisper's auto-detect for voice + Lingua-py for typed text (offline, local).
# Routes the chosen ISO 639-1 code to a Kokoro voice when supported, else macOS `say`.
# CONCEPT: language detection is unreliable on short strings, so we are sticky to English
#          unless confidence is high — this prevents "sure" from flipping to French.

"""Language detection + Kokoro/`say` voice routing for HER."""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Languages HER can talk in. Keep this list small to keep Lingua's classifier tight.
# CONCEPT: each entry maps an ISO 639-1 code to a Kokoro v1.0 voice, an espeak-ng
#          phonemizer language code, and a macOS `say` voice fallback (for languages
#          where Kokoro doesn't ship a voice or its tokenizer struggles).
@dataclass(frozen=True)
class LangProfile:
    code: str           # ISO 639-1 (e.g. "en", "hi")
    label: str          # Human-readable label for prompts/logs
    kokoro_voice: Optional[str]
    kokoro_lang: Optional[str]    # espeak-ng code Kokoro understands ("en-us", "fr-fr", …)
    say_voice: Optional[str]      # macOS `say -v <name>` fallback


# Order matters: the first one is the default (English).
PROFILES: dict[str, LangProfile] = {
    "en": LangProfile("en", "English", "af_heart", "en-us", "Samantha"),
    "es": LangProfile("es", "Spanish", "ef_dora", "es", "Monica"),
    "fr": LangProfile("fr", "French", "ff_siwis", "fr-fr", "Amelie"),
    "it": LangProfile("it", "Italian", "if_sara", "it", "Alice"),
    "pt": LangProfile("pt", "Portuguese", "pf_dora", "pt-br", "Luciana"),
    "hi": LangProfile("hi", "Hindi", "hf_alpha", "hi", "Lekha"),
    "ja": LangProfile("ja", "Japanese", "jf_alpha", "ja", "Kyoko"),
    "zh": LangProfile("zh", "Mandarin Chinese", "zf_xiaobei", "cmn", "Tingting"),
    # `say`-only fallbacks (Kokoro v1.0 has no voices for these on macOS).
    "de": LangProfile("de", "German", None, None, "Anna"),
    "ru": LangProfile("ru", "Russian", None, None, "Milena"),
    "ko": LangProfile("ko", "Korean", None, None, "Yuna"),
    "ar": LangProfile("ar", "Arabic", None, None, "Maged"),
    "nl": LangProfile("nl", "Dutch", None, None, "Xander"),
    "tr": LangProfile("tr", "Turkish", None, None, "Yelda"),
    "pl": LangProfile("pl", "Polish", None, None, "Zosia"),
    "sv": LangProfile("sv", "Swedish", None, None, "Alva"),
}

DEFAULT_LANG = "en"


def profile_for(code: Optional[str]) -> LangProfile:
    """Resolve any code (ISO 639-1, common Whisper codes) to a known profile."""
    if not code:
        return PROFILES[DEFAULT_LANG]
    c = code.strip().lower()
    # Whisper sometimes returns ISO 639-3 ("hin") or extended ("zh-cn"); coerce here.
    aliases = {
        "hin": "hi",
        "eng": "en",
        "spa": "es",
        "fra": "fr",
        "fre": "fr",
        "ita": "it",
        "por": "pt",
        "jpn": "ja",
        "zho": "zh",
        "chi": "zh",
        "zh-cn": "zh",
        "zh-tw": "zh",
        "deu": "de",
        "ger": "de",
        "rus": "ru",
        "kor": "ko",
        "ara": "ar",
        "nld": "nl",
        "tur": "tr",
        "pol": "pl",
        "swe": "sv",
        "cmn": "zh",
    }
    c = aliases.get(c, c)
    return PROFILES.get(c, PROFILES[DEFAULT_LANG])


# ---------------------------------------------------------------------------
# Text-side detection (Lingua-py).
# ---------------------------------------------------------------------------

# CONCEPT: build the detector once per process; loading the n-gram models is heavy.
_text_detector_lock = threading.Lock()
_text_detector = None  # type: ignore[var-annotated]


def _load_text_detector():
    """Build a cached Lingua detector restricted to PROFILES. Returns None if Lingua missing."""
    global _text_detector
    if _text_detector is not None:
        return _text_detector
    with _text_detector_lock:
        if _text_detector is not None:
            return _text_detector
        try:
            from lingua import Language, LanguageDetectorBuilder
        except Exception as exc:
            logger.info("Lingua-py not available (%s); falling back to heuristics.", exc)
            _text_detector = False  # sentinel: "tried + failed"
            return _text_detector
        # Map our ISO codes to Lingua's enum.
        wanted = []
        for code in PROFILES.keys():
            try:
                wanted.append(Language.from_iso_code_639_1(_iso_obj(code)))
            except Exception:
                continue
        if len(wanted) < 2:
            _text_detector = False
            return _text_detector
        _text_detector = LanguageDetectorBuilder.from_languages(*wanted).build()
        return _text_detector


def _iso_obj(code: str):
    """Convert a 2-letter code into Lingua's IsoCode639_1 enum value."""
    from lingua import IsoCode639_1  # local import: keeps import cost lazy
    return getattr(IsoCode639_1, code.upper())


def _has_non_latin_letter(text: str) -> bool:
    """True if `text` contains any letter outside the Latin script (kana, hangul, hanzi, devanagari…)."""
    import unicodedata
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch, "")
        except Exception:
            continue
        if "LATIN" not in name:
            return True
    return False


def detect_text_language(text: str) -> str:
    """Return ISO 639-1 code for `text`. Sticky to English on uncertainty/short input.

    Confidence policy (tuned on Lingua-py 2.2 confidence scores):
      • Empty / < 3 words / < 12 chars → DEFAULT_LANG (too short to trust).
      • Non-Latin script → trust Lingua's top guess (it's near-perfect on CJK/Devanagari).
      • Latin-script text → only flip if `top_conf ≥ 0.40` AND `top_conf − en_conf ≥ 0.25`.
        This catches confident hits like Spanish/French/German full sentences while leaving
        transliterated Hindi ("kya haal hai mere bhai") on English, which is the safe default.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return DEFAULT_LANG
    # CONCEPT: CJK languages don't use spaces, so word counts mislead. Switch the short-text
    # rule depending on script: word-count for Latin, raw letter-count for non-Latin.
    has_non_latin = _has_non_latin_letter(cleaned)
    if has_non_latin:
        # Need at least ~6 letters (kana/hanzi/devanagari) to be confident.
        letter_count = sum(1 for ch in cleaned if ch.isalpha())
        if letter_count < 6:
            return DEFAULT_LANG
    else:
        word_count = len(cleaned.split())
        if word_count < 3 or len(cleaned) < 12:
            return DEFAULT_LANG

    detector = _load_text_detector()
    if not detector:
        return DEFAULT_LANG  # graceful degrade — never block on language

    try:
        scores = detector.compute_language_confidence_values(cleaned)
    except Exception as exc:
        logger.debug("Lingua confidence call failed: %s", exc)
        return DEFAULT_LANG
    if not scores:
        return DEFAULT_LANG

    top = scores[0]
    top_iso = top.language.iso_code_639_1.name.lower()
    top_conf = float(top.value)
    if top_iso == DEFAULT_LANG:
        return DEFAULT_LANG
    if top_iso not in PROFILES:
        return DEFAULT_LANG  # we don't have a TTS path for it anyway.

    if has_non_latin:
        # Non-Latin scripts are unambiguous; Lingua hits 0.95+ here in practice.
        return top_iso if top_conf >= 0.50 else DEFAULT_LANG

    en_conf = next(
        (float(s.value) for s in scores if s.language.iso_code_639_1.name.lower() == "en"),
        0.0,
    )
    if top_conf >= 0.40 and (top_conf - en_conf) >= 0.25:
        return top_iso
    return DEFAULT_LANG


# ---------------------------------------------------------------------------
# macOS `say` availability.
# ---------------------------------------------------------------------------


def has_macos_say() -> bool:
    """True when /usr/bin/say is available (macOS only). Cheap to call repeatedly."""
    return shutil.which("say") is not None
