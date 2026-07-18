# Spoken alternates + "Correct that"

## Problem

This is *the* Dragon feature people miss the most when they switch. The flow:

1. User dictates: "I went to the *bach* on Saturday." (wanted "beach")
2. User says: **"Correct that."**
3. A small numbered overlay appears showing the n-best alternates:
   ```
   1. bach
   2. beach
   3. batch
   4. patch
   5. (spell it…)
   ```
4. User says: **"Choose 2."** Text in the document gets updated: "I went to the **beach** on Saturday."
5. The system also learns: "next time my voice produces this acoustic shape in this context, prefer 'beach'."

Today `correction_window.py` exists but is text-based ("type the correction") and doesn't use engine alternates — it only fuzzy-matches against the user dictionary. The most powerful correction signal — the engine's own n-best list — is thrown away.

## Solution

Three pieces.

### 1. Engine returns alternates

`engine/base.py` already has `TranscriptionSegment.words` as a typed-loose list. Extend `TranscriptionResult`:

```python
@dataclass
class TranscriptionAlternate:
    text: str
    score: float  # log-prob or rank

@dataclass
class TranscriptionSegment:
    text: str
    start: float
    end: float
    confidence: float = 0.0
    words: list = field(default_factory=list)
    alternates: list[TranscriptionAlternate] = field(default_factory=list)  # NEW
```

faster-whisper supports n-best when you set `beam_size>1` and pass `best_of=N` — the implementation in `faster_whisper_engine.py` needs to surface the secondary hypotheses, not just the top one.

For OpenAI API and Wispr cloud engines, n-best may or may not be available — when not, fall back to acoustic perturbation (transcribe the same segment with `temperature=0.4, 0.8` and dedupe).

### 2. "Correct that" command

Add to `data/default_commands.yaml`:

```yaml
- trigger: "correct that"
  action: "system.show_alternates"
  description: "Show alternates for the last transcription"

- trigger: "choose {number}"
  action: "system.choose_alternate"
  description: "Replace the last transcription with alternate N"
```

These need a new "system" action handler in `modes/command_mode.py` that pulls the last segment's alternates from a ring buffer (last 5 segments) maintained by the pipeline.

### 3. Alternates UI

A new compact overlay (`ui/alternates_overlay.py`) — distinct from the existing correction window. Appears near the cursor (or near the dictation box) on "correct that," shows the 4–6 alternates with numbers, accepts:

- Spoken "choose N" / "pick N"
- Number-key shortcut (1–6)
- Click
- "Spell it" → falls through to existing `correction_window` for manual correction
- Escape / "cancel that" → dismiss

When a selection is made:

1. Replace the document text. On Windows: send `Backspace × len(original)` then inject the chosen alternate. (Or use a smarter "select and replace" via the platform's text-substitution API — these vary by app.)
2. Add the (original, chosen) pair to `UserDictionary.add_correction` to bias future transcriptions.
3. Send the audio segment + corrected text to a (future) `data/learning/` directory if the user has opted into the [voice-profile-adaptive-lm](../04-differentiators/voice-profile-adaptive-lm.md) feature.

## Affected files

- `wispr_dragon/engine/base.py` — add `TranscriptionAlternate`, extend `TranscriptionSegment`.
- `wispr_dragon/engine/faster_whisper_engine.py` — surface n-best.
- `wispr_dragon/engine/openai_api_engine.py` — temperature-based alternate generation.
- `wispr_dragon/server/pipeline_runner.py` — maintain a ring buffer of recent segments (text, audio, alternates).
- New `wispr_dragon/ui/alternates_overlay.py`.
- `wispr_dragon/modes/command_mode.py` — handle `system.*` actions.
- `data/default_commands.yaml` — add the triggers.
- `wispr_dragon/correction/dictionary.py` — `add_correction` already exists; ensure it bumps frequency to the auto_apply_threshold.
- Tests: alternate generation, command routing, replace mechanics.

## Effort

Large. The overlay itself is small, but the engine-alternate surfacing and the cross-app "select and replace" mechanics are non-trivial.

## Gotchas

- **The "last transcription" anchor is fragile.** If the user has typed manually in between, you can't safely replace. Track an anchor token (e.g. a hash of the injected text) and verify before replacing — if it doesn't match, ask the user to highlight what to replace.
- **Multi-segment utterances**: "correct that" should target the *last segment*, not the whole session. Make this explicit in the UI ("Correcting: 'I went to the bach'").
- **Backspace-and-retype is destructive.** In Word/Pages, prefer the platform's "Select previous word and replace" if available, falling back to backspace.
- **Don't auto-apply alternates without confirmation.** Dragon's worst bug class is "I said correct, it interpreted my next word as the choice." Require an explicit "choose N" or click — never auto-pick.
