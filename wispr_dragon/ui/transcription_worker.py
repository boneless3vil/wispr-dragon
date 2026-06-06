"""Transcription worker thread — pulls audio from a queue, segments via VAD,
and transcribes complete speech segments.

Design:
- Audio callback pushes raw chunks into an unbounded-ish queue (non-blocking, fast).
- The worker thread drains the queue, feeds chunks to the VAD, and only invokes
  the transcription engine when VAD reports a complete speech segment (silence
  after speech). This matches the headless main-loop pattern and keeps the
  audio callback fast enough to avoid PortAudio dropouts.
"""

import logging
import queue
import time

import numpy as np

logger = logging.getLogger(__name__)

# Suppress repeated "queue full" warnings — log a summary at most once per N
# seconds so the terminal isn't flooded when transcription falls behind.
_QUEUE_FULL_WARN_INTERVAL_S = 2.0


class TranscriptionWorker:
    """Segment-driven transcription pipeline.

    Threading model:
    - `enqueue_chunk(chunk)` is called from the audio callback thread; it does
      a single non-blocking put and returns immediately.
    - `run()` is called from a dedicated worker thread. It blocks on the queue,
      runs VAD per chunk, and transcribes when a segment completes.
    - `stop()` may be called from any thread to break out of `run()`.
    """

    def __init__(
        self,
        engine,
        vad=None,
        post_processor=None,
        on_transcription=None,
        on_error=None,
        max_queue_size: int = 256,
        language: str = "en",
        beam_size: int = 10,
    ):
        """Initialize transcription worker.

        Args:
            engine: TranscriptionEngine instance (already loaded).
            vad: VoiceActivityDetector instance (already loaded). Required.
            post_processor: PostProcessor for text correction (optional).
            on_transcription: Callback when a final segment is ready. Signature:
                on_transcription(live: str, final: Optional[str]). For this
                worker, `live` is always "" and `final` carries the segment text.
            on_error: Callback on error (receives error message).
            max_queue_size: Cap on audio chunks waiting to be VAD'd. Past this,
                the oldest chunks are dropped (with a warning).
            language: Transcription language passed to the engine.
            beam_size: Decoder beam size passed to the engine.
        """
        self.engine = engine
        self.vad = vad
        self.post_processor = post_processor
        self.on_transcription = on_transcription
        self.on_error = on_error
        self.language = language
        self.beam_size = beam_size

        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_size)
        self._running = False
        self._drops_since_warn = 0
        self._last_drop_warn = 0.0

    def enqueue_chunk(self, chunk: np.ndarray) -> None:
        """Push a chunk from the audio thread. Never blocks."""
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            # Drop oldest and retry once so we keep the most recent audio.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(chunk)
                self._drops_since_warn += 1
                now = time.monotonic()
                if now - self._last_drop_warn >= _QUEUE_FULL_WARN_INTERVAL_S:
                    logger.warning(
                        "Transcription falling behind: dropped %d chunks in last %.1fs (queue=%d)",
                        self._drops_since_warn,
                        now - self._last_drop_warn if self._last_drop_warn else _QUEUE_FULL_WARN_INTERVAL_S,
                        self._queue.qsize(),
                    )
                    self._last_drop_warn = now
                    self._drops_since_warn = 0
            except queue.Empty:
                pass

    def run(self) -> None:
        """Main loop. Call from the transcription worker thread."""
        if self.vad is None:
            msg = "TranscriptionWorker requires a VAD instance"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            return

        self._running = True
        logger.info("Transcription worker started")

        chunks_seen = 0
        segments_seen = 0
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                # Ensure 1D float32 in [-1, 1]
                if chunk.ndim > 1:
                    chunk = chunk.flatten()
                if chunk.dtype != np.float32:
                    chunk = chunk.astype(np.float32)

                chunks_seen += 1
                if chunks_seen % 50 == 0:
                    logger.debug(
                        "Worker drained %d chunks, %d segments, queue=%d",
                        chunks_seen, segments_seen, self._queue.qsize(),
                    )

                segment = self.vad.process_chunk(chunk)
                if segment is None:
                    continue

                segments_seen += 1
                logger.info(
                    "VAD segment #%d: %.2fs of audio, queue=%d",
                    segments_seen, len(segment) / 16000, self._queue.qsize(),
                )

                result = self.engine.transcribe(
                    segment,
                    language=self.language,
                    beam_size=self.beam_size,
                )
                text = (result.text if result else "").strip()
                logger.info("Transcribed segment #%d: %r", segments_seen, text[:120])

                if not text:
                    continue

                if self.post_processor:
                    text = self.post_processor.process(text)

                if self.on_transcription:
                    self.on_transcription(live="", final=text)

            except Exception as e:
                logger.exception("Transcription error: %s", e)
                if self.on_error:
                    self.on_error(str(e))

        logger.info("Transcription worker stopped")

    def stop(self) -> None:
        """Signal the worker loop to exit. Safe to call from any thread."""
        self._running = False

    def reset(self) -> None:
        """Clear pending audio and reset VAD state."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if self.vad is not None:
            try:
                self.vad.reset()
            except Exception as e:
                logger.warning("VAD reset failed: %s", e)
