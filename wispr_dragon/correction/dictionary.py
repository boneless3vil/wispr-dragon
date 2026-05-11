"""Persistent user dictionary for word correction learning."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".wispr-dragon" / "user_dictionary.json"


class UserDictionary:
    """Stores and manages user corrections, custom words, and phrase replacements.

    This is the core of the Dragon-like learning system. When users correct
    transcription errors, those corrections are stored here and used to
    improve future transcriptions via hotword biasing and post-processing.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or DEFAULT_PATH
        self.corrections: dict[str, dict] = {}
        self.custom_words: list[str] = []
        self.phrase_replacements: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return

        with open(self.path) as f:
            data = json.load(f)

        self.corrections = data.get("corrections", {})
        self.custom_words = data.get("custom_words", [])
        self.phrase_replacements = data.get("phrase_replacements", {})
        logger.info(
            "Loaded dictionary: %d corrections, %d custom words, %d replacements",
            len(self.corrections), len(self.custom_words), len(self.phrase_replacements),
        )

    def _save(self) -> None:
        data = {
            "corrections": self.corrections,
            "custom_words": self.custom_words,
            "phrase_replacements": self.phrase_replacements,
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def add_correction(self, wrong: str, correct: str) -> None:
        """Record a correction from wrong text to correct text."""
        wrong_lower = wrong.lower().strip()
        correct = correct.strip()

        if correct.lower() not in [w.lower() for w in self.custom_words]:
            self.custom_words.append(correct)

        if wrong_lower in self.corrections:
            entry = self.corrections[wrong_lower]
            entry["correct"] = correct
            entry["frequency"] = entry.get("frequency", 0) + 1
            entry["last_used"] = datetime.now().isoformat()
            if wrong_lower not in entry.get("alternatives", []):
                entry["alternatives"].append(wrong_lower)
        else:
            self.corrections[wrong_lower] = {
                "correct": correct,
                "alternatives": [wrong_lower],
                "frequency": 1,
                "last_used": datetime.now().isoformat(),
            }

        self._save()
        logger.info("Added correction: '%s' -> '%s'", wrong, correct)

    def remove_correction(self, wrong: str) -> bool:
        """Remove a correction entry."""
        wrong_lower = wrong.lower().strip()
        if wrong_lower in self.corrections:
            del self.corrections[wrong_lower]
            self._save()
            return True
        return False

    def get_correction(self, text: str) -> Optional[str]:
        """Look up a correction for the given text."""
        entry = self.corrections.get(text.lower().strip())
        if entry:
            return entry["correct"]
        return None

    def get_high_confidence_corrections(self, threshold: int = 3) -> dict[str, str]:
        """Get corrections that have been made enough times to auto-apply."""
        return {
            wrong: entry["correct"]
            for wrong, entry in self.corrections.items()
            if entry.get("frequency", 0) >= threshold
        }

    def add_custom_word(self, word: str) -> None:
        """Add a custom word to the vocabulary."""
        if word not in self.custom_words:
            self.custom_words.append(word)
            self._save()

    def add_phrase_replacement(self, original: str, replacement: str) -> None:
        """Add a phrase replacement rule."""
        self.phrase_replacements[original.lower()] = replacement
        self._save()

    def build_hotwords(self, max_words: int = 100) -> str:
        """Build a hotwords string for Whisper from the dictionary.

        Prioritizes high-frequency corrections and custom words.
        """
        scored_words: list[tuple[int, str]] = []

        for entry in self.corrections.values():
            freq = entry.get("frequency", 1)
            scored_words.append((freq, entry["correct"]))

        for word in self.custom_words:
            if not any(w == word for _, w in scored_words):
                scored_words.append((0, word))

        scored_words.sort(key=lambda x: x[0], reverse=True)
        words = [w for _, w in scored_words[:max_words]]
        return ", ".join(words)

    def build_initial_prompt(self) -> str:
        """Build an initial_prompt string containing custom vocabulary.

        Whisper uses this as context to bias toward these words.
        """
        words = self.custom_words[:50]
        if not words:
            return ""
        return "The following names and terms may appear: " + ", ".join(words) + "."
