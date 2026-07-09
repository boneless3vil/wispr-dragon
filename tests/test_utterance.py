"""Unit tests for utterance-scoped transcription.

Covers the two pieces that make one-hotkey-press == one-transcription work:
``VoiceActivityDetector.trim`` (shave silence, never split) and
``PipelineRunner.process_utterance`` (transcribe the whole buffer in one pass).

Both are exercised with test doubles so no Silero model or Whisper weights are
needed — the real ones are covered by the e2e/integration tests.
"""

import numpy as np
import pytest

from wispr_dragon.audio.vad import VoiceActivityDetector
from wispr_dragon.config import Config
from wispr_dragon.server.pipeline_runner import PipelineRunner


# --- doubles ---------------------------------------------------------------

class _FakeVadModel:
    """Stands in for the Silero RNN; only reset_states() is used by trim()."""

    def __init__(self):
        self.resets = 0

    def reset_states(self):
        self.resets += 1


def _vad_with(stamps, **kwargs):
    """A VAD whose speech-timestamp lookup returns ``stamps``."""
    vad = VoiceActivityDetector(sample_rate=16000, **kwargs)
    vad._model = _FakeVadModel()
    vad._get_speech_timestamps = lambda *a, **k: stamps
    return vad


class _FakeResult:
    def __init__(self, text):
        self.text = text


class _FakeEngine:
    def __init__(self, text="hello there"):
        self.text = text
        self.calls = 0
        self.last_audio = None

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.last_audio = audio
        return _FakeResult(self.text)


class _FakePost:
    def process(self, text, apply_formatting=True):
        return text.strip()


class _TrimVad:
    """VAD double for process_utterance: records the audio it was handed."""

    def __init__(self, result):
        self.result = result
        self.trim_calls = 0

    def trim(self, audio):
        self.trim_calls += 1
        return self.result


def _runner(engine=None, vad=None):
    runner = PipelineRunner(Config())
    runner.engine = engine or _FakeEngine()
    runner.vad = vad
    runner.post_processor = _FakePost()
    runner.hotword_mgr = None
    runner.mode_mgr = None
    return runner


# --- vad.trim --------------------------------------------------------------

def test_trim_returns_speech_span():
    audio = np.ones(16000, dtype=np.float32)
    vad = _vad_with([{"start": 1000, "end": 5000}], speech_pad_ms=0,
                    min_speech_duration_ms=0)
    out = vad.trim(audio)
    assert out is not None
    assert len(out) == 4000


def test_trim_never_splits_across_an_internal_pause():
    """The whole point: a mid-sentence gap stays INSIDE one returned span."""
    audio = np.ones(16000, dtype=np.float32)
    # Two speech runs with a silent gap between them (a natural pause).
    vad = _vad_with(
        [{"start": 0, "end": 1000}, {"start": 9000, "end": 10000}],
        speech_pad_ms=0, min_speech_duration_ms=0,
    )
    out = vad.trim(audio)
    assert out is not None
    # Spans first onset -> last offset, gap included; not two fragments.
    assert len(out) == 10000


def test_trim_returns_none_on_silence():
    """An accidental hotkey tap has no speech and must not reach Whisper."""
    vad = _vad_with([], speech_pad_ms=0, min_speech_duration_ms=0)
    assert vad.trim(np.zeros(16000, dtype=np.float32)) is None


def test_trim_returns_none_when_below_min_speech():
    audio = np.ones(16000, dtype=np.float32)
    vad = _vad_with([{"start": 0, "end": 100}], speech_pad_ms=0,
                    min_speech_duration_ms=250)  # 4000 samples required
    assert vad.trim(audio) is None


def test_trim_padding_is_clamped_to_bounds():
    audio = np.ones(1000, dtype=np.float32)
    vad = _vad_with([{"start": 0, "end": 1000}], speech_pad_ms=100,
                    min_speech_duration_ms=0)
    out = vad.trim(audio)
    assert out is not None and len(out) == 1000  # no out-of-range slicing


def test_trim_resets_model_state_around_the_call():
    """Silero is a streaming RNN — state must not leak across utterances."""
    vad = _vad_with([{"start": 0, "end": 1000}], speech_pad_ms=0,
                    min_speech_duration_ms=0)
    vad.trim(np.ones(2000, dtype=np.float32))
    assert vad._model.resets >= 2  # before and after


def test_trim_raises_without_a_loaded_model():
    vad = VoiceActivityDetector()
    with pytest.raises(RuntimeError):
        vad.trim(np.zeros(100, dtype=np.float32))


def test_trim_handles_empty_audio():
    vad = _vad_with([{"start": 0, "end": 10}])
    assert vad.trim(np.zeros(0, dtype=np.float32)) is None


# --- process_utterance -----------------------------------------------------

def test_process_utterance_transcribes_whole_buffer_once():
    engine = _FakeEngine("one clean sentence")
    audio = np.ones(8000, dtype=np.float32)
    runner = _runner(engine, vad=_TrimVad(audio))
    assert runner.process_utterance(audio) == "one clean sentence"
    assert engine.calls == 1


def test_process_utterance_trims_before_transcribing():
    engine = _FakeEngine()
    trimmed = np.ones(500, dtype=np.float32)
    vad = _TrimVad(trimmed)
    runner = _runner(engine, vad=vad)
    runner.process_utterance(np.ones(8000, dtype=np.float32))
    assert vad.trim_calls == 1
    assert len(engine.last_audio) == 500, "engine should see the trimmed audio"


def test_process_utterance_skips_trim_when_disabled():
    engine = _FakeEngine()
    vad = _TrimVad(np.ones(10, dtype=np.float32))
    runner = _runner(engine, vad=vad)
    runner.process_utterance(np.ones(8000, dtype=np.float32), trim=False)
    assert vad.trim_calls == 0
    assert len(engine.last_audio) == 8000


def test_process_utterance_returns_empty_on_silence():
    """vad.trim() -> None means no speech; don't invent a transcript."""
    engine = _FakeEngine("hallucinated")
    runner = _runner(engine, vad=_TrimVad(None))
    assert runner.process_utterance(np.zeros(8000, dtype=np.float32)) == ""
    assert engine.calls == 0, "silence must never reach the engine"


def test_process_utterance_works_without_a_vad():
    engine = _FakeEngine("no vad")
    runner = _runner(engine, vad=None)
    assert runner.process_utterance(np.ones(8000, dtype=np.float32)) == "no vad"


def test_process_utterance_rejects_empty_and_bad_input():
    runner = _runner()
    assert runner.process_utterance(np.zeros(0, dtype=np.float32)) == ""
    assert runner.process_utterance("not an array") == ""


def test_process_utterance_returns_empty_without_engine():
    runner = _runner()
    runner.engine = None
    assert runner.process_utterance(np.ones(100, dtype=np.float32)) == ""
