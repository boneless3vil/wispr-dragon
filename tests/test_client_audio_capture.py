"""WindowsAudioCapture with a fake sounddevice stream (no audio hardware)."""

from __future__ import annotations

import asyncio
import time

import numpy as np

from wispr_dragon.client import audio_capture as ac


class FakeStream:
    def __init__(self, fail_after=None, cleanup_fails=False):
        self.reads = 0
        self.fail_after = fail_after
        self.cleanup_fails = cleanup_fails
        self.closed = False

    def start(self):
        pass

    def read(self, n):
        time.sleep(0.003)
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise RuntimeError("device unplugged")
        return np.zeros((n, 1), dtype=np.int16), False

    def stop(self):
        if self.cleanup_fails:
            raise RuntimeError("stop failed too")

    def close(self):
        self.closed = True


def _install(monkeypatch, *streams):
    queue = list(streams)
    made = []

    def factory(**kwargs):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        made.append(item)
        return item

    monkeypatch.setattr(ac.sd, "InputStream", factory)
    return made


def test_gate_keeps_frames_out_of_the_queue_while_the_link_is_down(monkeypatch):
    _install(monkeypatch, FakeStream())
    link = {"up": False}

    async def scenario():
        cap = ac.WindowsAudioCapture(gate=lambda: link["up"])
        cap.set_paused(False)
        queue = asyncio.Queue()
        task = asyncio.create_task(cap.start(queue))
        await asyncio.sleep(0.1)
        down = queue.qsize()
        link["up"] = True
        await asyncio.sleep(0.1)
        up = queue.qsize()
        cap.stop()
        await asyncio.wait_for(task, 2)
        return down, up

    down, up = asyncio.run(scenario())
    assert down == 0
    assert up > 0


def test_device_error_is_reported_and_cleanup_errors_are_swallowed(monkeypatch):
    made = _install(monkeypatch, FakeStream(fail_after=2, cleanup_fails=True))

    async def scenario():
        cap = ac.WindowsAudioCapture()
        await asyncio.wait_for(cap.start(asyncio.Queue()), 2)
        return cap

    cap = asyncio.run(scenario())
    assert cap.error == "device unplugged"
    assert made[0].closed, "stream is closed even though stop() raised"
    assert cap._stream is None


def test_open_failure_then_successful_retry(monkeypatch):
    _install(monkeypatch, RuntimeError("Invalid device"), FakeStream())

    async def scenario():
        cap = ac.WindowsAudioCapture()
        await asyncio.wait_for(cap.start(asyncio.Queue()), 2)
        first_error = cap.error
        task = asyncio.create_task(cap.start(asyncio.Queue()))
        await asyncio.sleep(0.05)
        cap.stop()
        await asyncio.wait_for(task, 2)
        return first_error, cap.error

    first_error, second_error = asyncio.run(scenario())
    assert first_error == "Invalid device"
    assert second_error is None


def test_full_queue_drops_frames_without_raising(monkeypatch):
    _install(monkeypatch, FakeStream())

    async def scenario():
        cap = ac.WindowsAudioCapture()
        cap.set_paused(False)
        queue = asyncio.Queue(maxsize=ac.CONTROL_HEADROOM + 2)
        task = asyncio.create_task(cap.start(queue))
        await asyncio.sleep(0.1)
        cap.stop()
        await asyncio.wait_for(task, 2)
        return queue.qsize(), cap._dropped, cap.error

    size, dropped, error = asyncio.run(scenario())
    # Audio stops short of maxsize: the last slots are kept for control frames.
    assert size == 2 and dropped > 0 and error is None
