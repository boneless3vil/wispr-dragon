"""End-to-end tests for server + client WebSocket mode.

Drives the real :class:`WebSocketServer` and :class:`WebSocketClient` against
each other over a loopback socket. The transcription pipeline is replaced with
a stub so the tests are fast and deterministic — the pipeline itself is covered
by its own unit tests. What these tests exercise is the *transport*: the
handshake, audio framing, transcript delivery, authentication, and the
reconnect-after-drop path.

Test functions are plain (synchronous) and drive asyncio via ``asyncio.run`` so
no pytest-asyncio / anyio plugin configuration is required.
"""

import asyncio
import socket

import numpy as np

from wispr_dragon.client.websocket_client import WebSocketClient
from wispr_dragon.server.websocket_server import WebSocketServer


# --- test doubles ----------------------------------------------------------

class FakePipeline:
    """Stub PipelineRunner — returns a canned transcript for any audio chunk."""

    def __init__(self, transcript="hello world"):
        self.transcript = transcript
        self.process_calls = 0

    def process(self, audio):
        self.process_calls += 1
        return self.transcript


class _ServerCfg:
    def __init__(self, host, port, api_key):
        self.host = host
        self.port = port
        self.api_key = api_key


class FakeConfig:
    """Minimal stand-in for Config — WebSocketServer only touches ``.server``."""

    def __init__(self, port, api_key=""):
        self.server = _ServerCfg("127.0.0.1", port, api_key)


# --- helpers ---------------------------------------------------------------

# 30 ms of silence at 16 kHz, int16 PCM — the frame size the client streams.
FRAME = np.zeros(480, dtype=np.int16).tobytes()


def _free_port():
    """Return an unused localhost TCP port."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _start_server(config, pipeline):
    """Start a WebSocketServer as a background task; return (server, task)."""
    server = WebSocketServer(config, pipeline)
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.3)  # let the listener bind
    return server, task


async def _stop_server(task):
    """Cancel a running server task and wait for it to unwind."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _feed_frames(queue, stop):
    """Continuously supply audio frames to the client until ``stop`` is set."""
    while not stop.is_set():
        try:
            queue.put_nowait(FRAME)
        except asyncio.QueueFull:
            pass
        await asyncio.sleep(0.01)


async def _wait_for(predicate, timeout=10.0):
    """Poll ``predicate`` until truthy or ``timeout`` seconds elapse."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def _drive_client(client, *, settle=0.0):
    """Run a client with a frame feeder; return (received, control coros).

    The caller awaits transcripts, then calls the returned ``stop()``.
    """
    received = []
    client.on_transcript = received.append
    queue = asyncio.Queue()
    stop = asyncio.Event()
    feeder = asyncio.create_task(_feed_frames(queue, stop))
    client_task = asyncio.create_task(client.run(queue))
    # Ensure run() has actually started before returning, so callers that
    # poll client._running don't observe the pre-start False.
    await _wait_for(lambda: client._running or client_task.done(), timeout=2)

    async def shutdown():
        stop.set()
        client.stop()
        await asyncio.gather(client_task, feeder, return_exceptions=True)

    if settle:
        await asyncio.sleep(settle)
    return received, shutdown


# --- tests -----------------------------------------------------------------

def test_transcript_roundtrip():
    """Client connects, streams audio, and receives the server's transcript."""

    async def scenario():
        port = _free_port()
        pipeline = FakePipeline("the quick brown fox")
        _, server_task = await _start_server(FakeConfig(port), pipeline)

        client = WebSocketClient(f"ws://127.0.0.1:{port}", api_key="")
        received, shutdown = await _drive_client(client)
        try:
            got = await _wait_for(lambda: len(received) > 0)
        finally:
            await shutdown()
            await _stop_server(server_task)

        assert got, "client never received a transcript"
        assert received[0] == "the quick brown fox"
        assert pipeline.process_calls > 0

    asyncio.run(scenario())


def test_auth_accepts_correct_key():
    """A client presenting the configured API key is served normally."""

    async def scenario():
        port = _free_port()
        pipeline = FakePipeline()
        _, server_task = await _start_server(
            FakeConfig(port, api_key="s3cret"), pipeline
        )

        client = WebSocketClient(f"ws://127.0.0.1:{port}", api_key="s3cret")
        received, shutdown = await _drive_client(client)
        try:
            got = await _wait_for(lambda: len(received) > 0)
        finally:
            await shutdown()
            await _stop_server(server_task)

        assert got, "correct key should be accepted"

    asyncio.run(scenario())


def test_auth_rejects_wrong_key():
    """A client with the wrong API key is rejected and gets no transcripts."""

    async def scenario():
        port = _free_port()
        pipeline = FakePipeline()
        _, server_task = await _start_server(
            FakeConfig(port, api_key="s3cret"), pipeline
        )

        errors = []
        client = WebSocketClient(
            f"ws://127.0.0.1:{port}", api_key="WRONG", on_error=errors.append
        )
        received, shutdown = await _drive_client(client)
        try:
            # The client should give up rather than reconnect-storm.
            stopped = await _wait_for(lambda: not client._running, timeout=5)
        finally:
            await shutdown()
            await _stop_server(server_task)

        assert received == [], "a rejected client must not receive transcripts"
        assert stopped, "client should stop itself on an auth rejection"

    asyncio.run(scenario())


def test_reconnect_after_server_restart():
    """The client reconnects on its own after the server drops and returns.

    Guards the reconnect fix: a dropped connection must not permanently kill
    the client, and a clean drop must still trigger the reconnect path.
    """

    async def scenario():
        port = _free_port()
        pipeline = FakePipeline()
        _, task1 = await _start_server(FakeConfig(port), pipeline)

        client = WebSocketClient(f"ws://127.0.0.1:{port}", api_key="")
        received, shutdown = await _drive_client(client)
        try:
            assert await _wait_for(lambda: len(received) > 0), "no transcript before drop"
            count_before = len(received)

            # Drop the server, then bring it back on the same port.
            await _stop_server(task1)
            await asyncio.sleep(0.5)
            _, task2 = await _start_server(FakeConfig(port), pipeline)

            try:
                reconnected = await _wait_for(
                    lambda: len(received) > count_before + 2, timeout=20
                )
            finally:
                await _stop_server(task2)
        finally:
            await shutdown()

        assert reconnected, "client did not reconnect after the server restarted"

    asyncio.run(scenario())
