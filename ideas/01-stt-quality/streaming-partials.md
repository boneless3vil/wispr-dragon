# Streaming partial transcription

## Problem

`server/pipeline_runner.py:97-148` is request/response: the VAD buffers audio until it sees `silence_duration_ms` of quiet, then ships the whole segment to the engine for transcription. Two consequences:

1. **Latency floor of `silence_duration_ms` + transcribe time.** Today that's 500 ms + ~300 ms on a small model — almost a second between "user stops talking" and "text appears."
2. **Long utterances feel broken.** Someone dictating a paragraph sees nothing for 10–30 seconds, then a wall of text. Users either lose trust ("is it working?") or break their own flow by pausing.

Dragon and modern competitors (Wispr Flow, MacWhisper, etc.) show *partial* results — text appears as you talk, then gets revised when the segment ends.

## Solution

Two-track transcription:

- **Hot track**: every 200–400 ms, transcribe the current speech buffer with `beam_size=1` and `condition_on_previous_text=False`. Emit as a `partial` message over the websocket. Don't inject.
- **Final track**: when VAD emits the segment, transcribe properly with the current `beam_size` and emit as `final`. The client replaces the partial with the final.

Engine interface change in `engine/base.py`:

```python
def transcribe_partial(self, audio_so_far: np.ndarray, **kwargs) -> str:
    """Best-effort low-latency transcript of an in-progress utterance."""
```

faster-whisper supports this directly (`beam_size=1, vad_filter=False, condition_on_previous_text=False`). The OpenAI API engine doesn't — it gets a no-op default that returns "".

Pipeline change in `pipeline_runner.py`: tap into the VAD's `_speech_buffer` (or pass a callback) so the runner gets a copy of the in-flight audio at a fixed cadence.

Wire format addition (the websocket protocol already exists per CLAUDE.md):

```json
{"type": "partial", "text": "the quick brown", "segment_id": 17}
{"type": "final",   "text": "The quick brown fox.", "segment_id": 17}
```

Client-side in `client/websocket_client.py`: track `segment_id`; on `partial`, render to a dimmed/italic overlay buffer; on `final`, commit. The Windows injector should NOT type partials — only finals get injected. The dictation box overlay (separate idea) is where partials show.

## Affected files

- `wispr_dragon/engine/base.py` — add `transcribe_partial` (with a default that returns "").
- `wispr_dragon/engine/faster_whisper_engine.py` — real implementation.
- `wispr_dragon/audio/vad.py` — expose the in-progress buffer or a partial-tick callback.
- `wispr_dragon/server/pipeline_runner.py` — schedule partial transcriptions on a timer thread, emit messages.
- `wispr_dragon/server/websocket_server.py` — new message types.
- `wispr_dragon/client/websocket_client.py` — handle `partial`/`final`.
- New `wispr_dragon/ui/dictation_box.py` (see [dictation-box](../03-dragon-parity/dictation-box.md)) — render partials.

## Effort

Medium. ~2 days for someone who knows the codebase. The hard part isn't the per-engine work, it's getting the timer + buffer access right without races. Use a single-flight pattern (drop a partial request if one is already in flight).

## Gotchas

- **GPU contention**: if partials and finals both compete for the GPU, finals get slower. Use a separate small/distilled model for partials (`distil-small.en`), or downgrade to int8 just for the partial path.
- **Don't inject partials.** Typing-then-retyping into the focused window is a UX disaster (and corrupts user typing). Partials are display-only; finals inject.
- **Resetting Silero state**: see `vad.py:99` — partials must not reset VAD state mid-utterance.
