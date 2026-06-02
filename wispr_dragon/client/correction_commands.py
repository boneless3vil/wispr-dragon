"""Pure parsing for client-side correction voice commands.

Kept Qt-free and IO-free so it is fully unit-testable. Two grammars:

  * the trigger that opens correction ("correct that"), recognized in the
    normal transcript stream;
  * the in-window selection grammar ("choose 2", bare number words, "cancel"),
    recognized only while the correction window is open.
"""

from __future__ import annotations

import re
from typing import Optional

# "correct that" / "correct this" — the open trigger. Also accept a trailing
# target ("correct <word>") but MVP only acts on the last utterance, so the
# target is captured for later phases and otherwise ignored.
_TRIGGER_RE = re.compile(r"^\s*correct\s+(that|this)\s*[.!?]?\s*$", re.IGNORECASE)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}

_CHOOSE_RE = re.compile(r"^\s*(?:choose|pick|select|number)\s+(\w+)\s*[.!?]?\s*$", re.IGNORECASE)
_CANCEL_RE = re.compile(r"^\s*(cancel|never mind|nevermind|escape)\s*[.!?]?\s*$", re.IGNORECASE)


def is_correct_trigger(text: str) -> bool:
    """True if ``text`` is the 'correct that' command."""
    return bool(_TRIGGER_RE.match(text or ""))


def _word_to_int(token: str) -> Optional[int]:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def parse_selection(text: str) -> Optional[dict]:
    """Parse an in-window selection utterance.

    Returns one of:
        {"action": "choose", "index": N}   (1-based list position)
        {"action": "cancel"}
    or None if the text isn't a recognized selection command (caller then
    treats it as a freehand correction candidate).
    """
    if not text:
        return None
    if _CANCEL_RE.match(text):
        return {"action": "cancel"}

    m = _CHOOSE_RE.match(text)
    if m:
        n = _word_to_int(m.group(1))
        if n is not None:
            return {"action": "choose", "index": n}
        return None

    # A bare number ("two", "3") also selects.
    n = _word_to_int(text.strip().rstrip(".!?"))
    if n is not None:
        return {"action": "choose", "index": n}

    return None
