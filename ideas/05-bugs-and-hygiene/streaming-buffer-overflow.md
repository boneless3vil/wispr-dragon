# VAD buffer overflow truncates utterances

## Problem

`audio/vad.py:104-114` guards against unbounded buffer growth — if speech continues past `max_buffer_seconds` (30 s by default), the buffer flushes mid-utterance:

```python
if buffer_size > self.max_buffer_samples and self._is_speaking:
    logger.warning("VAD buffer exceeded max size, flushing")
    segment = np.concatenate(self._speech_buffer)
    ...
    return segment
```

For someone dictating a long paragraph without pause, this produces a transcript that cuts off mid-thought, no warning to the user, just a fragment in their document.

## Fix

Two options:

1. **Emit and continue.** Instead of resetting `_is_speaking = False`, flush the current buffer as a segment *and* start a new buffer with the same speaking state. Whisper handles arbitrary-length input fine — the truncation is the bug, not the segmenting.
2. **Streaming partials make this moot.** If [streaming-partials](../01-stt-quality/streaming-partials.md) ships, long utterances get partial flushes anyway and never hit the limit.

Pick (1) as a small immediate fix even before partials lands.

## Affected

- `wispr_dragon/audio/vad.py:104-114`.
- `tests/` — add a test that feeds 40+ s of continuous speech and verifies no audio is lost.

## Effort

Trivial.
