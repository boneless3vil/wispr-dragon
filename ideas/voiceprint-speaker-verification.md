# Voiceprint speaker verification — design (approved, build after testing)

**Goal:** transcribe only the intended user's voice; ignore other people, a TV,
or a podcast in the background.

## Decisions (Jon, 2026-07-15)
- **Profiles:** multiple **single-user** profiles with a **selector menu** —
  create/train separate users, *select the active one*. Verify against the
  **currently-selected** profile's voiceprint (NOT N-way "match anyone").
- **Strictness:** **lenient** — bias toward never rejecting the real user (they
  pressed the hotkey); threshold is a dial they can tighten. False-reject-you is
  worse than occasionally letting a similar background voice through.
- **Timing:** implement **after** the current test pass + unsolved issues.

## Architecture (fits the existing utterance pipeline)
Per-utterance gate inside `pipeline_runner.process_utterance`, after `vad.trim()`,
before `_transcribe_and_format`:
```
trimmed = vad.trim(audio)
if verifier.enabled and not verifier.verify(trimmed, active_profile):
    return ""          # reuses the "empty result = send nothing" path
return _transcribe_and_format(trimmed)
```
Returning `""` means **no WebSocket protocol change** for the default
silent-drop. Optional "rejected: not you" feedback is an additive
`utterance_rejected` message behind a new `SERVER_FEATURES` entry
(`speaker_gate`) — only if we want UI feedback.

- **Deployment shapes:** verification runs **server-side** (shape B: thin Windows
  client never imports the model) or in-process (shape A: local `--ui`/headless).
- Audio is already 16 kHz mono float32 — no resampler needed.

## Model
- **Primary: SpeechBrain ECAPA-TDNN** (`spkrec-ecapa-voxceleb`) — Apache-2.0,
  ~85 MB, 192-dim, ~0.8% EER, shares torch/torchaudio with faster-whisper. Load
  once at pipeline `load()`; ~tens of ms/utterance on the RTX 4070.
- **Fallback: Resemblyzer** — light, weights bundled, offline, CPU-OK, weaker EER.
- Behind one interface so the choice is config/extra, not code.

## Enrollment
- Record 3–5 short phrases (~5 s each, ~20–30 s total after VAD-trim); more
  samples > one long read. Store L2-normalized **centroid + per-sample
  embeddings + model id** in `~/.wispr_dragon/voiceprints/<profile>.npz` (0600).
- Flows: CLI `--enroll [--profile NAME]`, `--reset-voiceprint`, list/select
  profiles; GUI "Enroll my voice" + profile selector menu (Jon's ask).
- Shape B (server): v1 = enroll via server-side CLI (no new protocol); later add
  `enroll_start/end` control frames behind the `speaker_gate` feature.

## Verification
- Cosine similarity of utterance embedding vs the **selected profile's** centroid.
- `threshold` (default ~0.25 for ECAPA — tune vs enrollment self-consistency),
  `margin` (0.05) gray band, `min_verify_ms` (1000 ms of trimmed speech).
- Lenient policy defaults: `on_too_short=accept`, `on_uncertain=accept`.

## Config (new `VoiceprintConfig`)
`enabled`(False) · `backend`(speechbrain|resemblyzer) · `active_profile`(default) ·
`threshold` · `margin` · `min_verify_ms` · `on_too_short` · `on_uncertain` ·
`enrollment_dir` · `notify_rejects`. Add validation + save-dict +
`tests/test_config_validation.py` (repo rule).

## File-by-file (for implementation)
- New `wispr_dragon/audio/speaker_verifier.py` — `load/embed/verify`, backend dispatch, lazy imports.
- New `wispr_dragon/audio/enrollment.py` — `enroll/load_voiceprint/reset/list_profiles`.
- `__main__.py` — `--enroll`, `--profile`, `--reset-voiceprint`, `--list-profiles`.
- `server/pipeline_runner.py` — build verifier in `load()`; gate in `process_utterance`.
- `server/websocket_server.py` — only if `notify_rejects`: `SERVER_FEATURES += ["speaker_gate"]`, emit `utterance_rejected`.
- `config.py`, `pyproject.toml` (`voiceprint` / `voiceprint-lite` extras), GUI (v1.1).

## Tests (deterministic)
Two in-repo voice samples (enrolled A, impostor B). Accept held-out A; reject B;
short-utterance policy; uncertain-band (stub embedder for fixed scores);
`process_utterance` gate returns "" and never calls transcribe on mismatch (mock
engine); config roundtrip. Real-model integration test behind a slow/extra guard.

## Known limits
Near-timbre TV voice or overlapping speech (user + TV at once) can slip through —
v2: target-speaker extraction / per-frame gating. Cold/whisper voice → re-enroll
or lower threshold. Same-gender close relatives are the hard tunable case.

_Full research + EER table + sources: architect memo (2026-07-15). Primary
sources: SpeechBrain spkrec-ecapa-voxceleb (HF), Resemblyzer (GitHub),
MDPI 2024 speaker-verification comparison._
