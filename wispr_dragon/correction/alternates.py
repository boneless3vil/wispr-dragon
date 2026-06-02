"""Synthesize a ranked list of alternative transcriptions for correction.

No STT engine here exposes true N-best beam hypotheses today (faster-whisper /
CTranslate2 don't surface beam runners-up; the cloud APIs return none), so the
correction window's "alternatives" are synthesized from what we *do* have:

  1. engine-supplied alternatives (real N-best) — empty today, highest priority
  2. a learned correction for this exact text (UserDictionary)
  3. homophones (Whisper's most common error class: their/there, to/too/two…)
  4. fuzzy neighbours among the user's custom vocabulary (rapidfuzz)

The original text is always included last. This module is pure (no Qt, no IO
beyond the dictionary object passed in) so it is fully unit-testable.

When real N-best lands, pass it in via ``engine_alternatives`` and it is
preferred over the synthesized sources — no interface change here.
"""

from __future__ import annotations

from typing import Optional

# Common English homophone / near-homophone clusters. Keyed lowercase; the
# lookup returns the *other* members of the cluster as candidates. Kept small
# and high-signal on purpose — this is not a dictionary, just the errors a
# speech model actually makes.
_HOMOPHONE_CLUSTERS: list[list[str]] = [
    ["their", "there", "they're"],
    ["to", "too", "two"],
    ["your", "you're"],
    ["its", "it's"],
    ["here", "hear"],
    ["new", "knew"],
    ["no", "know"],
    ["write", "right", "rite"],
    ["by", "buy", "bye"],
    ["for", "four", "fore"],
    ["one", "won"],
    ["wear", "where", "were"],
    ["weather", "whether"],
    ["aloud", "allowed"],
    ["peace", "piece"],
    ["principal", "principle"],
    ["affect", "effect"],
    ["accept", "except"],
    ["then", "than"],
]

_HOMOPHONE_INDEX: dict[str, list[str]] = {}
for _cluster in _HOMOPHONE_CLUSTERS:
    for _w in _cluster:
        _HOMOPHONE_INDEX[_w] = [o for o in _cluster if o != _w]


def homophones_for(text: str) -> list[str]:
    """Return homophone alternatives for a single word (case-preserving-ish)."""
    key = text.strip().lower()
    others = _HOMOPHONE_INDEX.get(key, [])
    if not others or not text.strip():
        return others
    # Mirror the original's capitalization for the first letter so a capitalized
    # word yields capitalized candidates ("Their" -> "There").
    if text.strip()[0].isupper():
        return [o[:1].upper() + o[1:] for o in others]
    return others


def synthesize_alternates(
    text: str,
    dictionary=None,
    engine_alternatives: Optional[list[str]] = None,
    limit: int = 6,
    fuzzy_cutoff: int = 60,
) -> list[str]:
    """Build a ranked, de-duplicated alternates list for ``text``.

    Args:
        text: the (possibly mis-recognized) text to offer alternatives for.
        dictionary: a UserDictionary (or None) for learned + custom-word sources.
        engine_alternatives: real N-best from the engine, if ever available.
        limit: max number of entries to return (including the original).
        fuzzy_cutoff: rapidfuzz score floor for custom-word neighbours.

    Returns:
        Ordered list of candidate strings, original always present (last unless
        it surfaces earlier). Never raises; missing rapidfuzz degrades to no
        fuzzy matches.
    """
    out: list[str] = []

    def _add(candidate: str) -> None:
        c = (candidate or "").strip()
        if c and c not in out:
            out.append(c)

    # 1. Real engine hypotheses first (empty today).
    for alt in engine_alternatives or []:
        _add(alt)

    # 2. Learned correction for this exact text.
    if dictionary is not None:
        existing = dictionary.get_correction(text)
        if existing:
            _add(existing)

    # 3. Homophones.
    for h in homophones_for(text):
        _add(h)

    # 4. Fuzzy neighbours among custom vocabulary.
    custom_words = getattr(dictionary, "custom_words", None) if dictionary else None
    if custom_words:
        try:
            from rapidfuzz import fuzz, process

            matches = process.extract(
                text, custom_words, scorer=fuzz.ratio,
                limit=limit, score_cutoff=fuzzy_cutoff,
            )
            for match_text, _score, _idx in matches:
                _add(match_text)
        except ImportError:
            pass

    # Original always offered (as a no-op choice), last.
    _add(text)

    return out[:limit]
