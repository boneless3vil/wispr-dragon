"""Per-mode text transforms for Dragon-equivalent Spelling and Numbers modes.

Each transformer turns the recognized words of one finalized segment into the
literal text that mode implies:

- **Spelling**: spoken letters / NATO words / "cap X" -> a contiguous character
  string (e.g. "cap a b c" -> "Abc", "alpha bravo" -> "ab").
- **Numbers**: spoken number words -> digits (e.g. "forty two" -> "42",
  "three point five" -> "3.5", "ten dollars" -> "$10").

The orchestrator looks up ``TRANSFORMERS[mode]`` and applies it to the dictation
output of the active mode. Transformers are pure functions of their input string
so they're trivially unit-testable without audio. If a transform can't make sense
of the input it returns the text unchanged rather than guessing.
"""

import re
from typing import Dict, List, Optional

from .mode_manager import Mode


class ModeTransformer:
    """Interface: turn recognized text into the active mode's literal output."""

    def transform(self, text: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


# --- Spelling -------------------------------------------------------------

_NATO = {
    "alpha": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e",
    "foxtrot": "f", "golf": "g", "hotel": "h", "india": "i", "juliet": "j",
    "juliett": "j", "kilo": "k", "lima": "l", "mike": "m", "november": "n",
    "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r", "sierra": "s",
    "tango": "t", "uniform": "u", "victor": "v", "whiskey": "w", "xray": "x",
    "x-ray": "x", "yankee": "y", "zulu": "z",
}

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

# Spoken punctuation usable while spelling.
_PUNCT_WORDS = {
    "period": ".", "dot": ".", "point": ".", "comma": ",", "dash": "-",
    "hyphen": "-", "underscore": "_", "space": " ", "slash": "/",
    "colon": ":", "semicolon": ";", "at": "@",
}

_CAP_WORDS = {"cap", "capital", "uppercase"}


class SpellingTransformer(ModeTransformer):
    """Convert spoken letters/NATO/digits into a contiguous character string."""

    def transform(self, text: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9'\-]+", text)
        if not tokens:
            return text

        out: List[str] = []
        cap_next = False
        for raw in tokens:
            tok = raw.lower()
            if tok in _CAP_WORDS:
                cap_next = True
                continue

            ch: Optional[str] = None
            if tok in _NATO:
                ch = _NATO[tok]
            elif tok in _DIGIT_WORDS:
                ch = _DIGIT_WORDS[tok]
            elif tok in _PUNCT_WORDS:
                ch = _PUNCT_WORDS[tok]
            elif len(tok) == 1 and (tok.isalpha() or tok.isdigit()):
                ch = tok

            if ch is None:
                # Unrecognized token (e.g. a whole word spoken in spelling mode):
                # append it verbatim rather than dropping it.
                ch = tok

            if cap_next:
                ch = ch.upper()
                cap_next = False
            out.append(ch)

        return "".join(out)


# --- Numbers --------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"and"}


def _classify(tok: str) -> Optional[str]:
    if tok in _UNITS:
        return "unit" if _UNITS[tok] < 10 else "teen"
    if tok in _TENS:
        return "tens"
    if tok in _SCALES:
        return "scale"
    return None


def _words_to_digits(tokens: List[str]) -> Optional[str]:
    """Convert integer number-words to a digit string, or None if not numeric.

    Words add up within a group ("twenty five" -> 25, "one hundred and five"
    -> 105), but a unit after a unit/teen, or a tens/teen after a
    unit/teen/tens, starts a new group, and groups are concatenated the way
    people read years and digit strings: "twenty twenty" -> "2020",
    "nineteen ninety nine" -> "1999", "five five five one two" -> "55512".
    Returned as a string so leading zeros survive ("zero two one" -> "021").
    """
    groups: List[str] = []
    total = current = 0
    prev: Optional[str] = None
    for tok in tokens:
        if tok == "and":
            continue
        kind = _classify(tok)
        if kind is None:
            return None
        if (kind == "unit" and prev in ("unit", "teen")) or (
            kind in ("tens", "teen") and prev in ("unit", "teen", "tens")
        ):
            groups.append(str(total + current))
            total = current = 0
        if tok == "hundred":
            current = (current or 1) * 100
        elif kind == "scale":
            total += (current or 1) * _SCALES[tok]
            current = 0
        else:
            current += _UNITS[tok] if tok in _UNITS else _TENS[tok]
        prev = kind
    if prev is None:
        return None
    groups.append(str(total + current))
    return "".join(groups)


class NumbersTransformer(ModeTransformer):
    """Convert spoken number words to digits, with decimals and simple currency.

    Text that already contains digits (Whisper often writes "10 dollars"
    itself) or that isn't a number phrase is returned unchanged.
    """

    def transform(self, text: str) -> str:
        if any(ch.isdigit() for ch in text):
            return text
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", text)]
        if not tokens:
            return text

        currency = False
        if tokens[-1] in ("dollar", "dollars"):
            currency = True
            tokens = tokens[:-1]

        # Split on "point" for a decimal fraction. Fraction words are read as
        # digits (Dragon behavior): "three point one four" -> 3.14, and
        # "oh"/"zero" are 0: "three point oh five" -> 3.05.
        if "point" in tokens:
            idx = tokens.index("point")
            int_tokens, frac_tokens = tokens[:idx], tokens[idx + 1:]
        else:
            int_tokens, frac_tokens = tokens, []

        if not int_tokens and not frac_tokens:
            return text  # e.g. a bare "dollars" or "point"

        int_digits = _words_to_digits(int_tokens) if int_tokens else "0"
        if int_digits is None:
            return text  # not a number phrase — leave it alone

        result = int_digits
        if frac_tokens:
            frac_digits = _words_to_digits(
                ["zero" if t == "oh" else t for t in frac_tokens]
            )
            if frac_digits is None:
                return text  # unrecognised fraction — don't guess or drop it
            result = f"{result}.{frac_digits}"

        if currency:
            result = f"${result}"
        return result


def build_transformers() -> Dict[Mode, ModeTransformer]:
    """Return the Mode -> transformer map for the orchestrator."""
    return {
        Mode.SPELLING: SpellingTransformer(),
        Mode.NUMBERS: NumbersTransformer(),
    }
