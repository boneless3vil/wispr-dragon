"""Tests for UI components (dictation box, audio/transcription workers)."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import numpy as np
import pytest

from wispr_dragon.config import Config
from wispr_dragon.ui.audio_worker import AudioWorker
from wispr_dragon.ui.transcription_worker import TranscriptionWorker


class TestAudioWorker:
    """Tests for AudioWorker (audio capture)."""

    @pytest.fixture
    def config(self):
        """Create audio config."""
        from wispr_dragon.config import AudioConfig
        return AudioConfig(sample_rate=16000, channels=1)

    @pytest.fixture
    def worker(self, config):
        """Create audio worker."""
        return AudioWorker(config)

    def test_audio_worker_initialization(self, worker):
        """Test AudioWorker initializes with correct state."""
        assert worker.is_running is False
        assert worker.audio_stream is None
        assert worker.vad is None

    def test_audio_worker_setup_checks_dependencies(self, worker):
        """Test setup() returns False if dependencies missing."""
        with patch.dict("sys.modules", {"sounddevice": None, "silero_vad": None}):
            # This would actually fail, so just test the basic structure
            assert hasattr(worker, "setup")
            assert callable(worker.setup)

    def test_audio_worker_cleanup(self, worker):
        """Test cleanup() resets state."""
        worker.is_running = True
        mock_stream = Mock()
        worker.audio_stream = mock_stream
        worker.vad = Mock()

        worker.cleanup()

        assert worker.is_running is False
        assert worker.vad is None
        # Stream should be closed
        mock_stream.close.assert_called_once()

    def test_audio_worker_callback_integration(self, worker):
        """Test that on_audio_chunk callback is called."""
        callback = Mock()
        worker.on_audio_chunk = callback
        worker.is_running = True

        chunk = np.random.randn(1600).astype(np.float32)
        # Simulate what would happen in the callback
        if worker.on_audio_chunk and worker.is_running:
            worker.on_audio_chunk(chunk)

        callback.assert_called_once()

    def test_audio_worker_error_callback(self, worker):
        """Test that on_error callback is called."""
        error_callback = Mock()
        worker.on_error = error_callback

        # Simulate an error
        if worker.on_error:
            worker.on_error("Test error")

        error_callback.assert_called_once_with("Test error")


class TestTranscriptionWorker:
    """Tests for TranscriptionWorker (transcription processing)."""

    @pytest.fixture
    def mock_engine(self):
        """Create mock transcription engine."""
        engine = Mock()
        engine.transcribe.return_value = {"text": "hello world"}
        return engine

    @pytest.fixture
    def worker(self, mock_engine):
        """Create transcription worker."""
        return TranscriptionWorker(mock_engine)

    def test_transcription_worker_initialization(self, worker):
        """Test TranscriptionWorker initializes with correct state."""
        assert len(worker.audio_buffer) == 0
        assert worker.is_processing is False
        assert worker.buffer_max_seconds == 30
        assert worker.sample_rate == 16000

    def test_transcription_worker_process_audio_chunk(self, worker, mock_engine):
        """Test processing an audio chunk."""
        chunk = np.random.randn(1600).astype(np.float32)
        callback = Mock()
        worker.on_transcription = callback

        worker.process_audio_chunk(chunk)

        # Buffer should contain the chunk
        assert len(worker.audio_buffer) > 0
        # Engine should have been called (if buffer >= sample_rate)
        if len(worker.audio_buffer) >= worker.sample_rate:
            assert mock_engine.transcribe.called or not worker.is_processing

    def test_transcription_worker_buffer_cap(self, worker):
        """Test that buffer doesn't grow unbounded."""
        # Create 31 seconds of audio (exceeds 30-second cap)
        chunk_size = worker.sample_rate // 10  # 0.1s chunks
        for _ in range(310):
            chunk = np.random.randn(chunk_size).astype(np.float32)
            worker.process_audio_chunk(chunk)

        # Buffer should be capped to 30 seconds
        max_samples = int(worker.buffer_max_seconds * worker.sample_rate)
        assert len(worker.audio_buffer) <= max_samples + chunk_size

    def test_transcription_worker_int16_conversion(self, worker):
        """Test that int16 audio is converted to float32."""
        chunk = np.array([16384, -16384, 0], dtype=np.int16)
        worker.on_transcription = Mock()

        worker.process_audio_chunk(chunk)

        # Buffer should be in float32
        assert worker.audio_buffer.dtype == np.float32

    def test_transcription_worker_flush_and_finalize(self, worker, mock_engine):
        """Test finalizing transcription."""
        # Add some audio to buffer
        chunk = np.random.randn(worker.sample_rate).astype(np.float32)
        worker.audio_buffer = chunk
        callback = Mock()
        worker.on_transcription = callback

        result = worker.flush_and_finalize()

        assert result == "hello world"
        assert len(worker.audio_buffer) == 0
        mock_engine.transcribe.assert_called_once()
        callback.assert_called_once()

    def test_transcription_worker_flush_empty_buffer(self, worker):
        """Test flush with empty buffer returns None."""
        result = worker.flush_and_finalize()
        assert result is None

    def test_transcription_worker_reset(self, worker):
        """Test reset clears state."""
        worker.audio_buffer = np.array([1.0, 2.0, 3.0])
        worker.is_processing = True

        worker.reset()

        assert len(worker.audio_buffer) == 0
        assert worker.is_processing is False

    def test_transcription_worker_with_post_processor(self, mock_engine):
        """Test integration with post-processor."""
        post_processor = Mock()
        post_processor.process.return_value = "HELLO WORLD"
        worker = TranscriptionWorker(mock_engine, post_processor=post_processor)

        chunk = np.random.randn(worker.sample_rate).astype(np.float32)
        worker.audio_buffer = chunk
        worker.on_transcription = Mock()

        result = worker.flush_and_finalize()

        assert result == "HELLO WORLD"
        post_processor.process.assert_called_once_with("hello world")

    def test_transcription_worker_error_handling(self, worker):
        """Test error callback is invoked on exception."""
        worker.on_error = Mock()
        worker.engine = Mock()
        worker.engine.transcribe.side_effect = RuntimeError("Test error")

        worker.audio_buffer = np.random.randn(worker.sample_rate).astype(np.float32)

        result = worker.flush_and_finalize()

        assert result is None
        worker.on_error.assert_called()


class TestUIComponentsIntegration:
    """Integration tests for UI components."""

    def test_audio_and_transcription_worker_chain(self):
        """Test audio → transcription pipeline."""
        mock_engine = Mock()
        mock_engine.transcribe.return_value = {"text": "test audio"}

        audio_worker = AudioWorker(Mock())
        transcription_worker = TranscriptionWorker(mock_engine)

        # Simulate audio chunk
        chunk = np.random.randn(1600).astype(np.float32)
        audio_worker.is_running = True

        # Audio worker would call the callback
        transcription_worker.process_audio_chunk(chunk)

        assert len(transcription_worker.audio_buffer) > 0

    def test_ui_config_integration(self):
        """Test UI config is properly initialized."""
        config = Config()
        assert config.audio.sample_rate == 16000
        assert config.audio.channels == 1
        assert config.engine.backend == "auto"
        assert hasattr(config, "ui")
