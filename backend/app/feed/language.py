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

# Non-English Latin function/content words.
# English high-frequency homographs removed (as/die/la/del/con/o/os/um/il/sono).
_LATIN_OTHER_MARKERS = re.compile(
    r"(?i)\b("
    r"le|les|des|une|du|au|aux|est|sont|dans|pour|avec|sur|par|qui|que|"
    r"conférence|extrait|présente|nouveau|nouvelle|nomme|gestion|"
    r"el|los|las|una|para|como|sobre|Congreso|Internacional|"
    r"der|das|und|für|mit|von|zur|im|"
    r"uma|dos|pelo|pela|"
    r"gli|della|delle|nel|nella"
    r")\b"
)

# Strong discriminators: near-zero in English tech wires.
# Marker hits with diacritics also count as strong (see _latin_other_by_markers).
# Weak markers (est/las/mit/sur/pour/par/von/der/dos/uma/como/…) stay in
# _LATIN_OTHER_MARKERS for the ≥3 unique-type count only.
_STRONG_MARKERS = frozenset(
    {
        # Task exemplars — unambiguous articles / particles
        "le",
        "les",
        "une",
        "für",
        "gli",
        # FR function / content (EN headline rarities; accented forms also auto-strong)
        "sont",
        "dans",
        "avec",
        "conférence",
        "extrait",
        "présente",
        # nouveau/nouvelle：EN 借词 + NVIDIA Nouveau 驱动名 → 弱词（仍在 marker 表计数）
        "nomme",
        "gestion",
        # ES orthography ≠ English International / Congress
        "congreso",
        "internacional",
        # IT / PT clitics & contractions
        "della",
        "delle",
        "nel",
        "nella",
        "pelo",
        "pela",
        # DE function words without common EN proper-name collision
        "und",
        "zur",
    }
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


def _latin_other_by_markers(text: str) -> bool:
    """Unique marker types ≥3 and at least one strong discriminator."""
    found = _LATIN_OTHER_MARKERS.findall(text)
    unique = {m.lower() for m in found}
    if len(unique) < 3:
        return False
    for m in unique:
        if m in _STRONG_MARKERS or _DIACRITIC.search(m):
            return True
    return False


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
        if _latin_other_by_markers(text):
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
