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


def _words_to_int(tokens: List[str]) -> Optional[int]:
    """Convert a list of integer number-words to an int, or None if not numeric."""
    if not tokens:
        return None
    current = 0
    total = 0
    saw_number = False
    for tok in tokens:
        if tok == "and":
            continue
        if tok in _UNITS:
            current += _UNITS[tok]
            saw_number = True
        elif tok in _TENS:
            current += _TENS[tok]
            saw_number = True
        elif tok == "hundred":
            current = (current or 1) * 100
            saw_number = True
        elif tok in _SCALES:
            total += (current or 1) * _SCALES[tok]
            current = 0
            saw_number = True
        else:
            return None
    if not saw_number:
        return None
    return total + current


class NumbersTransformer(ModeTransformer):
    """Convert spoken number words to digits, with decimals and simple currency."""

    def transform(self, text: str) -> str:
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", text)]
        if not tokens:
            return text

        currency = False
        if tokens and tokens[-1] in ("dollar", "dollars"):
            currency = True
            tokens = tokens[:-1]

        # Split on "point" for a decimal fraction; the fractional part is read
        # as individual digits (Dragon behavior): "three point one four" -> 3.14.
        if "point" in tokens:
            idx = tokens.index("point")
            int_tokens, frac_tokens = tokens[:idx], tokens[idx + 1:]
        else:
            int_tokens, frac_tokens = tokens, []

        int_val = _words_to_int(int_tokens) if int_tokens else 0
        if int_val is None:
            return text  # not a number phrase — leave it alone

        result = str(int_val)
        if frac_tokens:
            frac_digits = "".join(
                str(_UNITS[t]) for t in frac_tokens if t in _UNITS and _UNITS[t] < 10
            )
            if frac_digits:
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
