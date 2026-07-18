# Adaptive voice profile

## Problem

The user dictionary captures *corrections* (the user said X, Whisper heard Y, store the mapping). It doesn't capture the *positive* signal — words the user uses frequently and pronounces in a consistent way. Over a week of dictation, that's a lot of throwaway signal.

## Solution

Maintain a per-user adaptive prompt that gets appended to `initial_prompt` on every transcription. Three components:

1. **Frequent proper nouns** (extracted from the user's accepted transcripts) — names of people, projects, places.
2. **Domain vocabulary** (extracted from accepted text + the import-from-document flow in [command-vocabulary-browser](../03-dragon-parity/command-vocabulary-browser.md)).
3. **Recent corrections** (last N pairs, time-weighted) — biases the engine against the recurring mistakes.

```python
# wispr_dragon/correction/voice_profile.py
class VoiceProfile:
    def __init__(self, path: Path):
        self.path = path
        self.proper_nouns: Counter[str] = Counter()
        self.domain_terms: set[str] = set()
        self.recent_corrections: deque[tuple[str, str]] = deque(maxlen=50)

    def observe(self, transcript: str):
        # Run a small NER (spaCy en_core_web_sm or a regex+capitalization heuristic)
        # to find proper nouns; bump counts.
        ...

    def build_initial_prompt(self, max_tokens: int = 100) -> str:
        # Pick the top-K proper nouns by frequency, plus domain terms,
        # plus a few recent corrections as "context: X is the correct word for Y".
        top_nouns = [n for n, _ in self.proper_nouns.most_common(15)]
        return " ".join(top_nouns + list(self.domain_terms)[:10])
```

Wire into `pipeline_runner.process()`: after a final transcript is accepted (user didn't correct it within N seconds), `profile.observe(text)`. Before each transcribe, build the prompt and concatenate with the user's configured `initial_prompt`.

## Affected files

- New `wispr_dragon/correction/voice_profile.py`.
- `wispr_dragon/server/pipeline_runner.py` — wire observe + prompt.
- `wispr_dragon/correction/hotwords.py` — overlap; consolidate (hotwords are a special case of this).
- `wispr_dragon/config.py` — `VoiceProfileConfig` with enable flag and prompt-size budget.
- New `tests/test_voice_profile.py`.

## Effort

Medium. The hard part is *not* over-fitting — adaptive prompts can also bias against legitimately new words. Use exponential decay + a cap on prompt length.

## Gotchas

- **Privacy**: the profile contains the user's vocabulary, which can include sensitive content. Default to local-only storage; expose an "Export profile" + "Clear profile" UI.
- **Per-document context**: even better than a global profile is *per-document*. When the user is dictating into Doc A, prime the prompt with words extracted from Doc A's existing content. Out of scope for v1; mention as a future extension.
- **Cold start**: first week, the profile is empty and accuracy is unchanged. Don't promise a magical improvement on day 1.
