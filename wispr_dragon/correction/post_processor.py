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
    "new line": "\n",
    "new paragraph": "\n\n",
    "tab": "\t",
}

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
        text = self._apply_exact_corrections(text)
        text = self._apply_fuzzy_corrections(text)
        text = self._apply_phrase_replacements(text)
        if apply_formatting:
            text = self._apply_formatting(text)
        text = self._apply_capitalization_rules(text)
        if apply_formatting:
            # Last so an explicit spoken command beats the sentence-start
            # capitalizer and dictionary re-casing.
            text = self._apply_caps_commands(text)
        return text.strip()

    def _apply_exact_corrections(self, text: str) -> str:
        """Apply high-confidence exact-match corrections."""
        corrections = self.dictionary.get_high_confidence_corrections(
            self.auto_apply_threshold
        )
        for wrong, correct in corrections.items():
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            text = pattern.sub(correct, text)
        return text

    def _apply_fuzzy_corrections(self, text: str) -> str:
        """Apply fuzzy matching against the correction dictionary."""
        if not self.dictionary.corrections:
            return text

        words = text.split()
        known_wrongs = list(self.dictionary.corrections.keys())
        result = []
        i = 0
        while i < len(words):
            matched = False
            # Try matching 3-word, 2-word, then 1-word phrases
            for n in (3, 2, 1):
                if i + n > len(words):
                    continue
                phrase = " ".join(words[i:i + n]).lower()
                match = process.extractOne(
                    phrase, known_wrongs,
                    scorer=fuzz.ratio,
                    score_cutoff=self.fuzzy_threshold,
                )
                if match:
                    correction = self.dictionary.corrections[match[0]]["correct"]
                    result.append(correction)
                    i += n
                    matched = True
                    break
            if not matched:
                result.append(words[i])
                i += 1
        return " ".join(result)

    def _apply_phrase_replacements(self, text: str) -> str:
        """Apply phrase replacement rules."""
        for original, replacement in self.dictionary.phrase_replacements.items():
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            text = pattern.sub(replacement, text)
        return text

    def _apply_formatting(self, text: str) -> str:
        """Expand formatting commands like 'period', 'comma', 'new line'."""
        for command, replacement in FORMATTING_RULES.items():
            pattern = re.compile(r"\b" + re.escape(command) + r"\b", re.IGNORECASE)
            text = pattern.sub(replacement, text)
        # Clean up spaces before punctuation
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)
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
            return re.sub(r"[A-Za-z][\w']*",
                          lambda w: w.group(0)[0].upper() + w.group(0)[1:].lower(), s)

        # Span commands first: the next-word rules below would otherwise eat
        # "no caps on" as "no caps" + target "on". Bare "caps on" needs the
        # lookbehinds so it doesn't match the tail of the longer commands.
        text = span(r"\ball caps on", r"all caps off", str.upper)
        text = span(r"\bno caps on", r"no caps off", str.lower)
        text = span(r"(?<!\bno )(?<!\ball )\bcaps on", r"caps off", title)
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

        text = re.sub(r"[,.;:!?](?:\s*[,.;:!?])+", strongest, text)
        return text.replace(sentinel, "...")

    def _apply_capitalization_rules(self, text: str) -> str:
        """Auto-capitalize proper nouns from the dictionary.

        Skip common English stopwords to avoid over-capitalization.
        """
        for word in self.dictionary.custom_words:
            if word[0].isupper() and word.lower() not in STOPWORDS:
                pattern = re.compile(r"\b" + re.escape(word.lower()) + r"\b", re.IGNORECASE)
                text = pattern.sub(word, text)
        return text
