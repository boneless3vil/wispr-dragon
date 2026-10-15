"""Post-processing pipeline for transcription correction."""

import logging
import re

from rapidfuzz import fuzz, process

from .dictionary import UserDictionary

logger = logging.getLogger(__name__)

# Common English words that should never be auto-capitalized
# even if they appear in the custom words dictionary
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "not", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "can", "than", "then", "that",
    "this", "these", "those", "i", "you", "he", "she", "it", "we", "they",
}

# Built-in formatting commands for dictation mode
FORMATTING_RULES = {
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "exclamation point": "!",
    "exclamation mark": "!",
    "question mark": "?",
    "colon": ":",
    "semicolon": ";",
    "open quote": '"',
    "close quote": '"',
    "open paren": "(",
    "close paren": ")",
    "open parenthesis": "(",
    "close parenthesis": ")",
    # Whisper usually transcribes the spoken command as the plural.
    "open parentheses": "(",
    "close parentheses": ")",
    "left paren": "(",
    "right paren": ")",
    "hyphen": "-",
    "dash": " -- ",
    "ellipsis": "...",
    "tab": "\t",
}

# Line breaks are expanded separately: they swallow the spaces and any
# engine-inserted punctuation around the command ("Hello. New line. World."),
# and the later cleanup passes must never reach across them. Longest first.
NEWLINE_RULES = (
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
)


def _keyed_pattern(keys) -> "re.Pattern | None":
    """One case-insensitive alternation over ``keys``, longest first.

    Anchored so a key only matches whole words ("ai" never hits "again"), and
    a single pass means one rewrite can't feed another ("aa"->"bb"->"cc").
    """
    keys = sorted({k for k in keys if k}, key=len, reverse=True)
    if not keys:
        return None

    def bounded(key: str) -> str:
        # Word edges only where the key itself starts/ends with a word char,
        # so a key like ".com" still matches inside "example.com".
        return ((r"(?<!\w)" if re.match(r"\w", key) else "") + re.escape(key)
                + (r"(?!\w)" if re.search(r"\w$", key) else ""))

    return re.compile("|".join(map(bounded, keys)), re.IGNORECASE)


def _replace_keyed(text: str, mapping: dict[str, str]) -> str:
    """Replace every whole-word key of ``mapping`` (lowercase keys) literally."""
    pattern = _keyed_pattern(mapping)
    if pattern is None:
        return text
    # A function replacement, never a template: user text like "C:\Users"
    # must not be parsed for backreferences.
    return pattern.sub(lambda m: mapping.get(m.group(0).lower(), m.group(0)), text)


# Private-use marks fencing text the exact pass already rewrote; the fuzzy pass
# tokenizes a fenced span (whatever whitespace it holds) as one untouchable token.
_PROTECT_OPEN, _PROTECT_CLOSE = "\ue000", "\ue001"
_FUZZY_TOKEN = re.compile(r"\S*\ue000[^\ue001]*\ue001\S*|\S+")


def _protect(value: str) -> str:
    return _PROTECT_OPEN + value + _PROTECT_CLOSE


def _unprotect(text: str) -> str:
    return text.replace(_PROTECT_OPEN, "").replace(_PROTECT_CLOSE, "")


def _normalize(phrase: str) -> str:
    """Lowercase, punctuation-free, single-spaced — for fuzzy comparison."""
    return " ".join(re.sub(r"[^\w\s']", "", phrase).lower().split())

# Spoken capitalization commands handled by _apply_caps_commands:
#   "cap <word>"       -> Capitalize next word
#   "all caps <word>"  -> UPPERCASE next word
#   "no caps <word>"   -> lowercase next word
#   "caps on ... caps off"         -> Title Case the span
#   "all caps on ... all caps off" -> UPPERCASE the span
#   "no caps on ... no caps off"   -> lowercase the span
# Span commands run to end of utterance if the closing command never arrives.


class PostProcessor:
    """Applies corrections and formatting to raw transcription output.

    Pipeline order:
    1. Exact match replacements from dictionary
    2. Fuzzy match replacements for known corrections
    3. Auto-capitalization of proper nouns
    4. Formatting command expansion (dictation mode)
    """

    def __init__(self, dictionary: UserDictionary, fuzzy_threshold: int = 85,
                 auto_apply_threshold: int = 3):
        self.dictionary = dictionary
        self.fuzzy_threshold = fuzzy_threshold
        self.auto_apply_threshold = auto_apply_threshold

    def process(self, text: str, apply_formatting: bool = True) -> str:
        """Run the full post-processing pipeline."""
        # Exact rewrites are fenced off so the fuzzy pass can't re-match their
        # output ("jon" -> "Jon Baldwin" -> "Jon Baldwin Baldwin").
        text = self._apply_exact_corrections(text, protect=True)
        text = _unprotect(self._apply_fuzzy_corrections(text))
        text = self._apply_phrase_replacements(text)
        if apply_formatting:
            text = self._apply_formatting(text)
        text = self._apply_capitalization_rules(text)
        if apply_formatting:
            # Last so an explicit spoken command beats the sentence-start
            # capitalizer and dictionary re-casing.
            text = self._apply_caps_commands(text)
        # Spaces only: a spoken "new paragraph" on its own (the Dragon habit)
        # is an utterance whose whole output is a line break.
        return text.strip(" ")

    def _apply_exact_corrections(self, text: str, protect: bool = False) -> str:
        """Apply high-confidence exact-match corrections."""
        corrections = self.dictionary.get_high_confidence_corrections(
            self.auto_apply_threshold
        )
        if protect:
            corrections = {k: _protect(v) for k, v in corrections.items()}
        return _replace_keyed(text, corrections)

    def _apply_fuzzy_corrections(self, text: str) -> str:
        """Catch near-misses of corrections that are confident enough to auto-apply.

        Only entries at or above ``auto_apply_threshold`` qualify — a fix learned
        once is recorded (and biases the engine via hotwords) but isn't forced
        onto every similar-sounding word. Comparison ignores punctuation, an
        n-word window only matches an n-word key (so a neighbour isn't eaten),
        and the window's outer punctuation is carried over to the replacement.
        """
        by_len: dict[int, dict[str, str]] = {}
        for wrong, correct in self.dictionary.get_high_confidence_corrections(
            self.auto_apply_threshold
        ).items():
            key = _normalize(wrong)
            if key:
                by_len.setdefault(len(key.split()), {})[key] = correct
        if not by_len:
            return text

        words = _FUZZY_TOKEN.findall(text)
        result = []
        changed = False
        i = 0
        while i < len(words):
            for n in (3, 2, 1):
                candidates = by_len.get(n)
                if not candidates or i + n > len(words):
                    continue
                window = words[i:i + n]
                if any(_PROTECT_OPEN in w for w in window):
                    continue
                match = process.extractOne(
                    _normalize(" ".join(window)), list(candidates),
                    scorer=fuzz.ratio,
                    score_cutoff=self.fuzzy_threshold,
                )
                if match:
                    lead = re.match(r"^[^\w]*", window[0]).group(0)
                    trail = re.search(r"[^\w]*$", window[-1]).group(0)
                    result.append(lead + candidates[match[0]] + trail)
                    i += n
                    changed = True
                    break
            else:
                result.append(words[i])
                i += 1
        return " ".join(result) if changed else text

    def _apply_phrase_replacements(self, text: str) -> str:
        """Apply phrase replacement rules."""
        return _replace_keyed(text, {
            original.lower(): replacement
            for original, replacement in list(self.dictionary.phrase_replacements.items())
        })

    def _apply_formatting(self, text: str) -> str:
        """Expand formatting commands like 'period', 'comma', 'new line'."""
        for command, newline in NEWLINE_RULES:
            text = re.sub(r"[ \t]*\b" + command + r"\b[,.;:!?]?[ \t]*",
                          newline, text, flags=re.IGNORECASE)
        for command, replacement in FORMATTING_RULES.items():
            pattern = re.compile(r"\b" + re.escape(command) + r"\b", re.IGNORECASE)
            text = pattern.sub(lambda _m, r=replacement: r, text)
        # Clean up spaces before punctuation (never across a line break)
        text = re.sub(r"[ \t]+([.,!?;:])", r"\1", text)
        # Snug parens/quotes against their content: "( Control )" -> "(Control)"
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)
        # Collapse runs of adjacent punctuation to a single strongest mark. When
        # you *say* "comma"/"period", the engine also auto-punctuates from your
        # natural pauses, so the spoken mark collides with the model's own —
        # producing ",," or ".," ("Hello,, world.,, ..."). Keep ellipsis intact.
        text = self._collapse_adjacent_punctuation(text)
        # Capitalize first word after sentence-ending punctuation
        text = re.sub(r"([.!?]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), text)
        return text

    # Command word, optional engine-inserted punctuation, then the target word.
    # The engine auto-punctuates from pauses, so "no caps 26" often arrives as
    # "No caps, 26" — stray marks between command and target must be consumed.
    _CAPS_TARGET = r"[,.!?;:]*\s+([\w'-]+)"

    def _apply_caps_commands(self, text: str) -> str:
        """Consume spoken capitalization commands and re-case their target.

        "cap police" -> "Police", "all caps tomorrow" -> "TOMORROW",
        "no caps Tomorrow" -> "tomorrow". Spans: "caps on ... caps off"
        Title Cases, "all caps on ... all caps off" UPPERCASES, and
        "no caps on ... no caps off" lowercases everything between.
        """
        flags = re.IGNORECASE

        def span(on: str, off: str, recase) -> str:
            return re.sub(
                on + r"\b[,.!?;:]?\s*(.*?)(?:[,.!?;:]?\s*\b" + off + r"\b|$)",
                lambda m: recase(m.group(1)), text, flags=flags | re.DOTALL)

        def title(s: str) -> str:
            # Like Dragon: raise the first letter only, so "NASA"/"iPhone"
            # inside the span keep their inner capitals.
            return re.sub(r"[A-Za-z][\w']*",
                          lambda w: w.group(0)[0].upper() + w.group(0)[1:], s)

        # Span commands first: the next-word rules below would otherwise eat
        # "no caps on" as "no caps" + target "on". Bare "caps on" needs the
        # lookbehinds so it doesn't match the tail of the longer commands.
        text = span(r"\ball caps on", r"all caps off", str.upper)
        text = span(r"\bno caps on", r"no caps off", str.lower)
        text = span(r"(?<!\bno )(?<!\ball )\bcaps on", r"caps off", title)
        # An "off" with no "on" in this utterance (the span began in an earlier
        # one) is consumed, not treated as "all caps" + target "off". Bare
        # "caps off" is ordinary prose mid-sentence ("take your caps off"), so
        # it only counts as a command at the start or end of the utterance.
        text = re.sub(r"[ \t]*\b(?:all|no) caps off\b[,.!?;:]?", "", text, flags=flags)
        text = re.sub(r"^\s*caps off\b[,.!?;:]?|[ \t]*\bcaps off[,.!?;:]?\s*$", "",
                      text, flags=flags)
        text = re.sub(r"\ball caps" + self._CAPS_TARGET,
                      lambda m: m.group(1).upper(), text, flags=flags)
        text = re.sub(r"\bno caps" + self._CAPS_TARGET,
                      lambda m: m.group(1).lower(), text, flags=flags)
        text = re.sub(r"\bcap" + self._CAPS_TARGET,
                      lambda m: m.group(1).capitalize(), text, flags=flags)
        return text

    # Higher wins when several marks land next to each other.
    _PUNCT_PRIORITY = {"?": 5, "!": 4, ".": 3, ";": 2, ":": 2, ",": 1}

    def _collapse_adjacent_punctuation(self, text: str) -> str:
        """Reduce a run of ``,.;:!?`` (optionally space-separated) to one mark.

        Parentheses and quotes are left alone. Ellipsis (``...``) is protected so
        it isn't crushed to a single dot.
        """
        sentinel = "\x00ELLIPSIS\x00"
        text = text.replace("...", sentinel)

        def strongest(match: re.Match) -> str:
            marks = [c for c in match.group(0) if c in self._PUNCT_PRIORITY]
            return max(marks, key=self._PUNCT_PRIORITY.__getitem__)

        text = re.sub(r"[,.;:!?](?:[ \t]*[,.;:!?])+", strongest, text)
        return text.replace(sentinel, "...")

    def _apply_capitalization_rules(self, text: str) -> str:
        """Auto-capitalize proper nouns from the dictionary.

        Skip common English stopwords to avoid over-capitalization.
        """
        for word in list(self.dictionary.custom_words):
            if word and word[0].isupper() and word.lower() not in STOPWORDS:
                pattern = re.compile(r"\b" + re.escape(word.lower()) + r"\b", re.IGNORECASE)
                text = pattern.sub(lambda _m, w=word: w, text)
        return text
