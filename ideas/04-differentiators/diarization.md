# Speaker diarization

## Problem

Wispr Dragon is a single-user dictation app today. But the audio pipeline can transcribe arbitrary audio, and meeting transcription is one of the highest-value use cases STT has — both for personal use (review my standup) and team use (post-meeting summary).

## Solution

Optional diarization pass that runs alongside the engine:

```python
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
diar = pipeline(audio_file)  # returns Annotation with speaker labels per range
```

Output format adds `speaker` to each segment:

```python
@dataclass
class TranscriptionSegment:
    text: str
    start: float
    end: float
    speaker: Optional[str] = None  # NEW
    ...
```

Triggered manually (a "transcribe meeting" mode, not the live dictation path) — pyannote is slow enough that running it inline would tank latency. The flow:

1. User clicks "Record meeting" → audio captured to a wav file in `~/.wispr_dragon/recordings/`.
2. User stops → pipeline transcribes + diarizes asynchronously.
3. Output: markdown transcript like `**Speaker A** (0:12): ...` opens in the dictation box.

## Effort

Medium. Diarization is well-supported by pyannote. Most of the work is the recording UI (record/pause/stop, file management) and the offline-transcription job runner.

## Gotcha

- **Pyannote license**: pyannote-audio requires accepting the HuggingFace gated model agreement. Document it; don't bundle the model in installer.
- **Naming speakers**: users want "Alice / Bob," not "Speaker A / Speaker B." A post-step where the user types in names per speaker chunk is essential — and re-applies to future meetings via voice fingerprint matching (out of scope v1).
