# Spelling & Numbers modes

## Problem

CLAUDE.md says:

> **Modes**: dictation, command, spelling, numbers. We have `modes/` — extend it as we add Dragon-equivalent modes.

Today `modes/command_mode.py` is the only mode file. Spelling and numbers are missing. These matter because:

- **Spelling mode**: when the user dictates an unusual name, code identifier, or acronym, Whisper guesses. In spelling mode every character is taken literally — "a, p, p, l, e" → "apple". Crucial for code, technical names, IDs.
- **Numbers mode**: "one hundred and twenty three point four five" → "123.45" reliably, and inhibit the spoken-punctuation expansion so phone numbers don't end up with hyphens-as-the-word-hyphen.

## Solution

Two new processors that run *post-engine* (not separate engines):

### `modes/spelling_mode.py`

```python
class SpellingPostProcessor:
    """Convert spoken letters/digits into a tight literal string."""

    PHONETIC = {
        "alpha": "a", "bravo": "b", "charlie": "c", # ... NATO alphabet
        "ay": "a", "bee": "b", "cee": "c", # ... say-the-letter variants
    }

    def process(self, text: str) -> str:
        tokens = text.lower().split()
        out = []
        for tok in tokens:
            tok = tok.rstrip(".,;")
            if tok in self.PHONETIC:
                out.append(self.PHONETIC[tok])
            elif tok in {"space": " ", "dash": "-", "underscore": "_",
                         "dot": ".", "at": "@", "slash": "/"}:
                out.append(tok)
            elif len(tok) == 1 and tok.isalpha():
                out.append(tok)
            elif tok in DIGIT_WORDS:
                out.append(DIGIT_WORDS[tok])
            # else: ignore — spelling mode is strict
        return "".join(out)
```

### `modes/numbers_mode.py`

```python
import word2number.w2n as w2n

class NumbersPostProcessor:
    def process(self, text: str) -> str:
        try:
            value = w2n.word_to_num(text)
            return str(value)
        except ValueError:
            # Fall through to a regex-based mixed-mode parser for
            # "one twenty-three" / "point" / "decimal" / phone-number cadences.
            return self._mixed_parse(text)
```

Use `word2number` for the common case; ship a hand-rolled fallback for decimal, currency, phone-number cadences.

### Mode manager

The pipeline already imports `modes.mode_manager.ModeManager`. Extend it:

```python
class Mode(str, Enum):
    DICTATION = "dictation"
    COMMAND = "command"
    SPELLING = "spelling"
    NUMBERS = "numbers"
```

Mode switch commands (in `data/default_commands.yaml`):

```yaml
- trigger: "spelling mode"
  action: "system.set_mode"
  mode: "spelling"
- trigger: "numbers mode"
  action: "system.set_mode"
  mode: "numbers"
- trigger: "dictation mode"
  action: "system.set_mode"
  mode: "dictation"
- trigger: "stop spelling"  # natural exit
  action: "system.set_mode"
  mode: "dictation"
```

`pipeline_runner.process()` routes the post-engine text through the right mode processor before injecting.

## Affected files

- New `wispr_dragon/modes/spelling_mode.py`, `wispr_dragon/modes/numbers_mode.py`.
- `wispr_dragon/modes/mode_manager.py` — extend enum + dispatch.
- `wispr_dragon/server/pipeline_runner.py` — call the right post-processor by mode.
- `data/default_commands.yaml` — mode-switch triggers.
- `wispr_dragon/ui/tray.py` (when built) — mode submenu.
- Tests: `tests/test_spelling_mode.py`, `tests/test_numbers_mode.py`.

## Effort

Small to medium. Spelling mode is small. Numbers mode's edge cases (decimals, fractions, ordinals, phone numbers, "twenty oh seven" for years) are where the complexity hides.

## Gotcha

Mode should auto-revert to dictation after one utterance? Or stay? Dragon stays. Match Dragon. Add an option for the other behavior.
