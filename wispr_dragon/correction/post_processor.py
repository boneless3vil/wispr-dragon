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
    "hyphen": "-",
    "dash": " -- ",
    "ellipsis": "...",
    "new line": "\n",
    "new paragraph": "\n\n",
    "tab": "\t",
}

CAPITALIZATION_COMMANDS = {
    "cap": "capitalize_next",
    "caps on": "capitalize_on",
    "caps off": "capitalize_off",
    "all caps": "uppercase_next",
    "no caps": "lowercase_next",
}


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
        # Capitalize first word after sentence-ending punctuation
        text = re.sub(r"([.!?]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), text)
        return text

    def _apply_capitalization_rules(self, text: str) -> str:
        """Auto-capitalize proper nouns from the dictionary.

        Skip common English stopwords to avoid over-capitalization.
        """
        for word in self.dictionary.custom_words:
            if word[0].isupper() and word.lower() not in STOPWORDS:
                pattern = re.compile(r"\b" + re.escape(word.lower()) + r"\b", re.IGNORECASE)
                text = pattern.sub(word, text)
        return text
