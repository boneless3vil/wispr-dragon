"""Shared trigger-phrase normalisation and ``{placeholder}`` pattern compilation.

Used by both the built-in command registry (``modes/command_mode.py``) and the
macro runner (``macros/macro_runner.py``) so the two matchers agree on how a
spoken utterance lines up with a trigger phrase.
"""

import logging
import re
from functools import lru_cache
from typing import Optional, Pattern

logger = logging.getLogger(__name__)

# Sentence punctuation Whisper / the post-processor wrap around a short command
# ("Open browser." / "Scratch that!").
_EDGE_PUNCT = ".!?,;:"
_PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)\}")
_INNER_PUNCT = re.compile(r"[^\w\s']+")


def normalize_utterance(text: str) -> str:
    """Lowercase, collapse whitespace, and strip edge punctuation (``.!?,;:``)."""
    return " ".join(text.lower().split()).strip(_EDGE_PUNCT + " ")


def normalize_phrase(text: str) -> str:
    """Normalise for whole-phrase comparison: like :func:`normalize_utterance`
    but every punctuation mark except apostrophes becomes a word break, so
    "Scratch, that." == "scratch that" while "that's" stays one word."""
    return " ".join(_INNER_PUNCT.sub(" ", text.lower()).split())


def has_placeholder(trigger: str) -> bool:
    """True if the trigger uses (or tries to use) ``{placeholder}`` syntax."""
    return "{" in trigger or "}" in trigger


@lru_cache(maxsize=1024)
def compile_trigger(trigger: str) -> Optional[Pattern[str]]:
    """Compile a ``{placeholder}`` trigger into a pattern for ``fullmatch``.

    Literal text is matched case-insensitively; each ``{name}`` captures one or
    more words. Compiled once per distinct trigger (cached). Returns None, after
    logging a warning, for a malformed trigger (stray brace, invalid or
    duplicated placeholder name) so one bad user macro can't raise ``re.error``
    in the middle of dictation.
    """
    norm = " ".join(trigger.split()).strip(_EDGE_PUNCT + " ")
    parts = []
    pos = 0
    for m in _PLACEHOLDER.finditer(norm):
        parts.append(norm[pos:m.start()].lower())
        parts.append(m.group(1))
        pos = m.end()
    parts.append(norm[pos:].lower())

    literals = parts[0::2]
    if any("{" in lit or "}" in lit for lit in literals):
        logger.warning("Ignoring trigger with malformed placeholder: %r", trigger)
        return None

    body = "".join(
        re.escape(part) if i % 2 == 0 else rf"(?P<{part}>[\w\s]+)"
        for i, part in enumerate(parts)
    )
    try:
        return re.compile(body, re.IGNORECASE)
    except re.error as e:
        logger.warning("Ignoring trigger %r: %s", trigger, e)
        return None


def match_placeholder(trigger: str, normalized_text: str) -> Optional[dict]:
    """Match already-normalised text against a placeholder trigger.

    Returns the captured ``{name: value}`` dict (values stripped), or None if
    the trigger is malformed or doesn't match the whole utterance.
    """
    pattern = compile_trigger(trigger)
    if pattern is None:
        return None
    m = pattern.fullmatch(normalized_text)
    if not m:
        return None
    return {k: v.strip() for k, v in m.groupdict().items()}
