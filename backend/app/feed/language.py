"""Feed language gate — English-first; native JA/ZH ok; no EN→JA/ZH translations.

Policy (user 2026-07-12 + DESIGN §3.0.1):
- Primarily English originals.
- Small amount of **native** Japanese / Chinese allowed (can tighten later).
- Never keep English wires that were translated into Chinese or Japanese
  (neither in source intake nor in LLM summaries).
- French / Spanish / German / Portuguese / Italian / etc. → reject.
"""

from __future__ import annotations

import re
from typing import Literal

Lang = Literal["en", "ja", "zh", "other"]

# Letters with diacritics common in FR/ES/DE/PT/IT (not typical in English wires)
_DIACRITIC = re.compile(
    r"[àâäæçéèêëîïôœùûüÿáíóúñãõäöüßÀÂÄÆÇÉÈÊËÎÏÔŒÙÛÜŸÁÍÓÚÑÃÕÄÖÜẞ]"
)

# Strong function-word hits for non-English Latin languages
_LATIN_OTHER_MARKERS = re.compile(
    r"(?i)\b("
    r"le|la|les|des|une|du|au|aux|est|sont|dans|pour|avec|sur|par|qui|que|"
    r"conférence|extrait|présente|nouveau|nouvelle|nomme|gestion|"
    r"el|los|las|una|del|con|para|como|sobre|Congreso|Internacional|"
    r"der|die|das|und|für|mit|von|zur|im|"
    r"o|os|as|um|uma|dos|das|pelo|pela|"
    r"il|gli|della|delle|nel|nella|sono"
    r")\b"
)

_HIRAGANA = re.compile(r"[\u3040-\u309F]")
_KATAKANA = re.compile(r"[\u30A0-\u30FF]")
_CJK = re.compile(r"[\u4E00-\u9FFF]")
_LATIN = re.compile(r"[A-Za-z]")


def _script_counts(text: str) -> dict[str, int]:
    return {
        "latin": len(_LATIN.findall(text)),
        "cjk": len(_CJK.findall(text)),
        "hira": len(_HIRAGANA.findall(text)),
        "kata": len(_KATAKANA.findall(text)),
        "diacritic": len(_DIACRITIC.findall(text)),
    }


def classify_language(title: str, content: str = "") -> Lang:
    """Heuristic language class for title (+ optional body head)."""
    text = f"{title or ''}\n{(content or '')[:800]}"
    if not text.strip():
        return "en"
    c = _script_counts(text)
    # Japanese: kana present
    if c["hira"] + c["kata"] >= 2:
        return "ja"
    # Chinese: CJK without kana, and CJK dominates Latin
    if c["cjk"] >= 8 and c["cjk"] >= c["latin"] * 0.6:
        return "zh"
    # Latin path
    if c["latin"] >= 12:
        if c["diacritic"] >= 3:
            return "other"
        if len(_LATIN_OTHER_MARKERS.findall(text)) >= 3:
            return "other"
        return "en"
    if c["cjk"] >= 4:
        return "zh"
    return "en" if c["latin"] >= c["cjk"] else "other"


def language_allowed(title: str, content: str = "") -> tuple[bool, Lang]:
    """Source-text gate: EN / native JA / native ZH ok; Romance etc. rejected."""
    lang = classify_language(title, content)
    return lang in ("en", "ja", "zh"), lang


def is_translated_from_english(title: str, summary: str) -> bool:
    """English (or other-Latin) title + JA/ZH summary → LLM translated; reject.

    Native JA/ZH sources have JA/ZH titles, so they pass.
    Mixed summaries (ticker names + Chinese body) still count as ZH/JA.
    """
    if not summary or not title:
        return False
    src = classify_language(title, "")
    out = classify_language(summary, "")
    if src == "en" and out in ("zh", "ja"):
        return True
    # English title + summary with substantial CJK/kana despite Latin tickers
    if src in ("en", "other"):
        c = _script_counts(summary)
        if c["hira"] + c["kata"] >= 2:
            return True
        if c["cjk"] >= 6:
            return True
        if src == "other":
            tc = _script_counts(title)
            if tc["latin"] >= 12 and out in ("zh", "ja"):
                return True
    return False


# Back-compat alias
def looks_like_en_to_zh_translation(title: str, summary: str) -> bool:
    return is_translated_from_english(title, summary)
