"""Shared dictation pipeline: post-process -> mode/command dispatch -> mode transform.

Both the headless loop (`main.py`) and the floating dictation box (`UIController`)
route finalized transcript segments through here so command handling, sleep/wake,
and (Feature 2) spelling/numbers transforms behave identically instead of drifting.

Path-specific *actions* (undo, correction, macro execution) are registered as
handlers on the supplied `ModeManager` by each caller — the headless path injects
text into the focused window, while the UI path edits the on-screen buffer — so
those handlers genuinely differ and are not centralized here.

The server pipeline (`server/pipeline_runner.py`) intentionally does NOT use this:
it streams transcribed text to a remote client that performs injection, so command
execution server-side would require a WebSocket protocol change (out of scope).
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .mode_manager import Mode, ModeManager

logger = logging.getLogger(__name__)


@dataclass
class TranscriptOutcome:
    """Result of routing one finalized transcript segment through the pipeline.

    Exactly one of the two states holds:
    - ``text`` set        -> dictation output to display and/or inject.
    - ``consumed`` True    -> the utterance was a command, mode switch, or arrived
                              in sleep mode; it produced no dictation text. Any side
                              effect (undo, macro, keystroke) already fired via a
                              registered handler.
    """

    text: Optional[str] = None
    consumed: bool = False

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())


class DictationOrchestrator:
    """Routes finalized transcript segments through post-processing and the modes.

    Args:
        post_processor: PostProcessor applying dictionary corrections + formatting.
        mode_manager: ModeManager owning the active mode and command dispatch. The
            caller registers its path-specific handlers on this before/after
            constructing the orchestrator.
        transformers: optional ``{Mode: transformer}`` map where each transformer
            exposes ``transform(str) -> str``. Populated by Feature 2 (spelling /
            numbers); an empty map means plain dictation formatting only.
    """

    def __init__(
        self,
        post_processor,
        mode_manager: ModeManager,
        transformers: Optional[Dict[Mode, Any]] = None,
    ):
        self.post_processor = post_processor
        self.mode_manager = mode_manager
        self.transformers: Dict[Mode, Any] = dict(transformers) if transformers else {}

    @property
    def mode(self) -> Mode:
        return self.mode_manager.mode

    def handle_transcript(self, raw_text: str) -> TranscriptOutcome:
        """Route one finalized transcript segment.

        Returns a :class:`TranscriptOutcome` — either text to emit, or
        ``consumed=True`` when the utterance was handled as a command / mode
        switch and produced no dictation output.
        """
        if not raw_text or not raw_text.strip():
            return TranscriptOutcome(consumed=True)

        # Auto-formatting (capitalization, spacing) only makes sense for free
        # dictation; command/spelling/numbers modes manage their own form.
        apply_formatting = self.mode_manager.mode == Mode.DICTATION
        processed = self.post_processor.process(raw_text, apply_formatting=apply_formatting)

        output = self.mode_manager.process_text(processed)
        if output is None:
            # Consumed as a command, mode switch, or swallowed in sleep mode.
            return TranscriptOutcome(consumed=True)

        # Apply the active mode's transform (spelling/numbers) to dictation output.
        transformer = self.transformers.get(self.mode_manager.mode)
        if transformer is not None:
            output = transformer.transform(output)

        return TranscriptOutcome(text=output)
