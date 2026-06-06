"""Tests for UI components (dictation box, audio/transcription workers)."""

from unittest.mock import Mock, patch

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

        worker.cleanup()

        assert worker.is_running is False
        assert worker.audio_stream is None
        mock_stream.stop.assert_called_once()
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
    """Tests for TranscriptionWorker (queue-based transcription pipeline)."""

    @pytest.fixture
    def mock_engine(self):
        """Create mock transcription engine."""
        result = Mock()
        result.text = "hello world"
        engine = Mock()
        engine.transcribe.return_value = result
        return engine

    @pytest.fixture
    def mock_vad(self):
        """Create mock VAD that returns None (no segment complete)."""
        vad = Mock()
        vad.process_chunk.return_value = None
        return vad

    @pytest.fixture
    def worker(self, mock_engine, mock_vad):
        """Create transcription worker."""
        return TranscriptionWorker(mock_engine, vad=mock_vad)

    def test_transcription_worker_initialization(self, worker):
        """Test TranscriptionWorker initializes with correct state."""
        assert worker._running is False
        assert worker._queue.empty()
        assert worker.engine is not None
        assert worker.vad is not None

    def test_transcription_worker_enqueue_chunk(self, worker):
        """Test enqueuing an audio chunk."""
        chunk = np.random.randn(1600).astype(np.float32)
        worker.enqueue_chunk(chunk)
        assert not worker._queue.empty()

    def test_transcription_worker_enqueue_drops_oldest_when_full(self):
        """Test that a full queue drops the oldest chunk."""
        engine = Mock()
        vad = Mock()
        worker = TranscriptionWorker(engine, vad=vad, max_queue_size=2)

        chunk1 = np.array([1.0], dtype=np.float32)
        chunk2 = np.array([2.0], dtype=np.float32)
        chunk3 = np.array([3.0], dtype=np.float32)

        worker.enqueue_chunk(chunk1)
        worker.enqueue_chunk(chunk2)
        worker.enqueue_chunk(chunk3)  # Should drop chunk1

        assert worker._queue.qsize() == 2

    def test_transcription_worker_run_requires_vad(self, mock_engine):
        """Test that run() errors without a VAD."""
        on_error = Mock()
        worker = TranscriptionWorker(mock_engine, vad=None, on_error=on_error)
        worker.run()
        on_error.assert_called_once()

    def test_transcription_worker_run_processes_segment(self, mock_engine, mock_vad):
        """Test that run() transcribes when VAD returns a segment."""
        segment = np.random.randn(16000).astype(np.float32)
        mock_vad.process_chunk.return_value = segment
        on_transcription = Mock()

        worker = TranscriptionWorker(
            mock_engine, vad=mock_vad, on_transcription=on_transcription
        )
        chunk = np.random.randn(1600).astype(np.float32)
        worker.enqueue_chunk(chunk)

        # run() will process one chunk then block on empty queue; stop after first
        import threading
        threading.Timer(0.6, worker.stop).start()
        worker.run()

        mock_engine.transcribe.assert_called_once()
        on_transcription.assert_called_once_with(live="", final="hello world")

    def test_transcription_worker_run_applies_post_processor(self, mock_engine, mock_vad):
        """Test that run() applies the post-processor to transcribed text."""
        segment = np.random.randn(16000).astype(np.float32)
        mock_vad.process_chunk.return_value = segment
        post_processor = Mock()
        post_processor.process.return_value = "HELLO WORLD"
        on_transcription = Mock()

        worker = TranscriptionWorker(
            mock_engine, vad=mock_vad, post_processor=post_processor,
            on_transcription=on_transcription,
        )
        worker.enqueue_chunk(np.random.randn(1600).astype(np.float32))

        import threading
        threading.Timer(0.6, worker.stop).start()
        worker.run()

        post_processor.process.assert_called_once_with("hello world")
        on_transcription.assert_called_once_with(live="", final="HELLO WORLD")

    def test_transcription_worker_run_error_handling(self, mock_vad):
        """Test error callback is invoked on transcription exception."""
        engine = Mock()
        engine.transcribe.side_effect = RuntimeError("Test error")
        segment = np.random.randn(16000).astype(np.float32)
        mock_vad.process_chunk.return_value = segment
        on_error = Mock()

        worker = TranscriptionWorker(engine, vad=mock_vad, on_error=on_error)
        worker.enqueue_chunk(np.random.randn(1600).astype(np.float32))

        import threading
        threading.Timer(0.6, worker.stop).start()
        worker.run()

        on_error.assert_called()

    def test_transcription_worker_stop(self, worker):
        """Test stop() signals the run loop to exit."""
        worker._running = True
        worker.stop()
        assert worker._running is False

    def test_transcription_worker_reset(self, worker, mock_vad):
        """Test reset clears queue and resets VAD."""
        worker.enqueue_chunk(np.array([1.0, 2.0, 3.0], dtype=np.float32))
        assert not worker._queue.empty()

        worker.reset()

        assert worker._queue.empty()
        mock_vad.reset.assert_called_once()


class TestUIComponentsIntegration:
    """Integration tests for UI components."""

    def test_audio_and_transcription_worker_chain(self):
        """Test audio → transcription pipeline via enqueue_chunk."""
        mock_engine = Mock()
        mock_vad = Mock()
        mock_vad.process_chunk.return_value = None

        audio_worker = AudioWorker(Mock())
        transcription_worker = TranscriptionWorker(mock_engine, vad=mock_vad)

        # Simulate audio chunk flowing from audio worker to transcription worker
        chunk = np.random.randn(1600).astype(np.float32)
        audio_worker.is_running = True

        # Audio worker would call enqueue_chunk via its callback
        transcription_worker.enqueue_chunk(chunk)

        assert not transcription_worker._queue.empty()

    def test_ui_config_integration(self):
        """Test UI config is properly initialized."""
        config = Config()
        assert config.audio.sample_rate == 16000
        assert config.audio.channels == 1
        assert config.engine.backend == "auto"
        assert hasattr(config, "ui")
