"""Unit tests for the OpenAI API engine's local helpers (no network)."""

import io
import wave

import numpy as np

from wispr_dragon.engine.openai_api_engine import _api_model_name, _to_wav


def test_local_model_sizes_map_to_hosted_whisper():
    assert _api_model_name("small.en") == "whisper-1"
    assert _api_model_name("") == "whisper-1"
    assert _api_model_name("gpt-4o-transcribe") == "gpt-4o-transcribe"


def test_silence_encodes_without_nan():
    buf = _to_wav(np.zeros(1600, dtype=np.float32))
    with wave.open(buf) as wav:
        frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        assert wav.getframerate() == 16000 and wav.getnchannels() == 1
    assert frames.size == 1600 and not frames.any()


def test_audio_is_clipped_not_normalized():
    quiet = np.full(10, 0.1, dtype=np.float32)
    loud = np.full(10, 3.0, dtype=np.float32)
    for audio, expected in ((quiet, int(0.1 * 32767)), (loud, 32767)):
        with wave.open(_to_wav(audio)) as wav:
            frames = np.frombuffer(wav.readframes(10), dtype="<i2")
        assert abs(int(frames[0]) - expected) <= 1
    assert isinstance(_to_wav(quiet), io.BytesIO)
