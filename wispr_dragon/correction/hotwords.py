"""Dynamic hotword list builder for Whisper biasing."""

from .dictionary import UserDictionary


class HotwordManager:
    """Builds and manages hotword lists and initial prompts for Whisper.

    Dynamically generates the initial_prompt and hotwords parameters
    from the user dictionary to bias Whisper toward known vocabulary.
    """

    def __init__(self, dictionary: UserDictionary, max_hotwords: int = 100):
        self.dictionary = dictionary
        self.max_hotwords = max_hotwords
        self._session_words: list[str] = []

    def add_session_word(self, word: str) -> None:
        """Add a word encountered during this session for extra biasing."""
        if word not in self._session_words:
            self._session_words.append(word)

    def get_hotwords(self) -> str:
        """Get the current hotwords string for faster-whisper."""
        base = self.dictionary.build_hotwords(self.max_hotwords)
        if self._session_words:
            session = ", ".join(self._session_words[-20:])
            return f"{base}, {session}" if base else session
        return base

    def get_initial_prompt(self) -> str:
        """Get the current initial_prompt string for Whisper."""
        return self.dictionary.build_initial_prompt()

    def reset_session(self) -> None:
        """Clear session-specific words."""
        self._session_words.clear()
