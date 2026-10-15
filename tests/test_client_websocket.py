"""Client-side WebSocket behaviour against stub servers.

Unlike test_server_client_e2e.py (real server), these drive
:class:`WebSocketClient` against tiny ``websockets.serve`` stubs, so each test
can make the server misbehave in exactly one way: refuse with 4000/4001, drop
the connection right after ``ready``, or send transcripts that make the app
callback raise.

Plain synchronous tests driving ``asyncio.run`` (no async plugin needed).
"""

import asyncio
import json
import socket

import websockets

from wispr_dragon.client import websocket_client as wsc
from wispr_dragon.client.websocket_client import WebSocketClient

FRAME = b"\x00\x00" * 480


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _serve(handler):
    port = _free_port()
    server = await websockets.serve(handler, "127.0.0.1", port)
    return server, f"ws://127.0.0.1:{port}"


async def _wait_for(predicate, timeout=5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def _stop(client, task, server=None, timeout=5.0):
    # Generous: on Windows a refused localhost connect takes ~2 s to fail.
    client.stop()
    await asyncio.wait_for(task, timeout)
    if server is not None:
        server.close()
        await server.wait_closed()


READY = json.dumps({"type": "ready", "server_version": "test", "features": []})


# --- reconnect storm (close 4000) ------------------------------------------

def test_busy_server_4000_backs_off_instead_of_storming():
    """Regression: a server refusing with 4000 ("already connected") after the
    handshake used to reset the backoff counter on every handshake, so the
    client reconnected in a tight loop (~885 handshakes in 2 s)."""

    async def scenario():
        handshakes = 0

        async def handler(ws):
            nonlocal handshakes
            handshakes += 1
            await ws.close(code=4000, reason="already_connected")

        server, url = await _serve(handler)
        statuses = []
        client = WebSocketClient(url, api_key="", on_status=statuses.append)
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await asyncio.sleep(2.5)
            running = client._running
        finally:
            await _stop(client, task, server)
        return handshakes, running, statuses

    handshakes, running, statuses = asyncio.run(scenario())
    assert 1 <= handshakes <= 3, f"reconnect storm: {handshakes} handshakes in 2.5 s"
    assert running, "a busy server is transient — the client must keep retrying"
    assert "busy" in statuses


def test_handshake_alone_does_not_reset_backoff():
    """The counter resets on `ready`, not when the HTTP upgrade succeeds."""

    async def scenario():
        async def handler(ws):
            await ws.close(code=4000, reason="already_connected")

        server, url = await _serve(handler)
        client = WebSocketClient(url, api_key="")
        client._reconnect_count = 3
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: client._reconnect_count != 3, timeout=3)
            count = client._reconnect_count
        finally:
            await _stop(client, task, server)
        return count

    assert asyncio.run(scenario()) == 4


def test_ready_resets_backoff():
    async def scenario():
        async def handler(ws):
            await ws.send(READY)
            await ws.wait_closed()

        server, url = await _serve(handler)
        client = WebSocketClient(url, api_key="")
        client._reconnect_count = 5
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            reset = await _wait_for(lambda: client._reconnect_count == 0, timeout=5)
        finally:
            await _stop(client, task, server)
        return reset

    assert asyncio.run(scenario())


def test_lost_connection_always_backs_off():
    """A server that accepts (sends ready) and then drops us at once must not
    be reconnected to in a tight loop either."""

    async def scenario():
        handshakes = 0

        async def handler(ws):
            nonlocal handshakes
            handshakes += 1
            await ws.send(READY)
            await ws.close()

        server, url = await _serve(handler)
        client = WebSocketClient(url, api_key="")
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await asyncio.sleep(2.5)
        finally:
            await _stop(client, task, server)
        return handshakes

    handshakes = asyncio.run(scenario())
    assert 1 <= handshakes <= 2, f"{handshakes} handshakes in 2.5 s"


def test_stop_cuts_a_backoff_wait_short():
    """Quit must not hang for up to 32 s while the client waits to reconnect."""

    async def scenario():
        client = WebSocketClient(f"ws://127.0.0.1:{_free_port()}", api_key="")
        task = asyncio.create_task(client.run(asyncio.Queue()))
        await _wait_for(lambda: client._reconnect_count >= 1, timeout=5)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await _stop(client, task, timeout=2)
        return loop.time() - started

    assert asyncio.run(scenario()) < 1.0


def test_reconnect_now_skips_the_backoff_wait():
    async def scenario():
        client = WebSocketClient(f"ws://127.0.0.1:{_free_port()}", api_key="")
        attempts = []
        real_open = client._open_socket

        async def counting_open():
            attempts.append(1)
            return await real_open()

        client._open_socket = counting_open
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: len(attempts) == 1 and client._reconnect_count >= 1)
            client.reconnect_now()
            retried = await _wait_for(lambda: len(attempts) >= 2, timeout=1.0)
        finally:
            await _stop(client, task)
        return retried

    assert asyncio.run(scenario()), "settings change should retry at once, not after 2 s"


# --- auth failure (close 4001) ---------------------------------------------

def test_auth_failure_stops_without_retrying():
    async def scenario():
        handshakes = 0

        async def handler(ws):
            nonlocal handshakes
            handshakes += 1
            await ws.close(code=4001, reason="unauthorized")

        server, url = await _serve(handler)
        statuses = []
        client = WebSocketClient(url, api_key="WRONG", on_status=statuses.append)
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await asyncio.wait_for(task, 5)  # ends on its own
        finally:
            server.close()
            await server.wait_closed()
        await asyncio.sleep(0.3)
        return handshakes, client.auth_failed, statuses

    handshakes, auth_failed, statuses = asyncio.run(scenario())
    assert handshakes == 1, "a rejected key must not be retried (reconnect storm)"
    assert auth_failed
    assert "unauthorized" in statuses


# --- callbacks can't drop the link -----------------------------------------

def test_raising_transcript_callback_does_not_drop_the_connection():
    async def scenario():
        handshakes = 0

        async def handler(ws):
            nonlocal handshakes
            handshakes += 1
            await ws.send(READY)
            for i in range(3):
                await ws.send(json.dumps({"type": "transcript", "text": f"t{i}"}))
            await ws.wait_closed()

        server, url = await _serve(handler)
        calls = []

        def on_transcript(text):
            calls.append(text)
            raise RuntimeError("injection blew up")

        client = WebSocketClient(url, api_key="", on_transcript=on_transcript)
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: len(calls) == 3, timeout=5)
            await asyncio.sleep(0.2)
        finally:
            await _stop(client, task, server)
        return calls, handshakes

    calls, handshakes = asyncio.run(scenario())
    assert calls == ["t0", "t1", "t2"]
    assert handshakes == 1, "a callback exception must not tear the connection down"


# --- stale audio -------------------------------------------------------------

def test_stale_queue_is_discarded_on_connect():
    """Audio queued before the link came up must not reach the server."""

    async def scenario():
        received = []

        async def handler(ws):
            await ws.send(READY)
            async for message in ws:
                received.append(message)

        server, url = await _serve(handler)
        queue = asyncio.Queue()
        for _ in range(50):
            queue.put_nowait(FRAME)
        client = WebSocketClient(url, api_key="")
        task = asyncio.create_task(client.run(queue))
        try:
            await _wait_for(lambda: client.is_connected, timeout=5)
            await asyncio.sleep(0.3)
            stale = len(received)
            queue.put_nowait({"type": "utterance_start", "id": "fresh"})
            await _wait_for(lambda: len(received) > stale, timeout=3)
        finally:
            await _stop(client, task, server)
        return stale, received

    stale, received = asyncio.run(scenario())
    assert stale == 0, f"{stale} stale frames were sent after reconnecting"
    assert json.loads(received[-1])["id"] == "fresh", "live frames still flow"


# --- bounded shutdown ------------------------------------------------------

class _HangingSocket:
    open = True

    async def close(self):
        await asyncio.sleep(60)


def test_disconnect_is_bounded_on_a_dead_network(monkeypatch):
    monkeypatch.setattr(wsc, "_CLOSE_WAIT_S", 0.2)

    async def scenario():
        client = WebSocketClient("ws://unused", api_key="")
        client.websocket = _HangingSocket()
        await asyncio.wait_for(client.disconnect(), 2)
        return client.websocket

    assert asyncio.run(scenario()) is None


def test_connect_sets_a_short_close_timeout(monkeypatch):
    seen = {}

    async def fake_connect(url, **kwargs):
        seen.update(kwargs)
        return _HangingSocket()

    monkeypatch.setattr(wsc.websockets, "connect", fake_connect)

    async def scenario():
        client = WebSocketClient("ws://example:1", api_key="k")
        return await client.connect()

    assert asyncio.run(scenario()) is True
    assert seen["close_timeout"] == wsc._CLOSE_TIMEOUT_S <= 2
    assert seen["extra_headers"] == {"Authorization": "Bearer k"}


# --- review follow-ups --------------------------------------------------------

def test_transcripts_are_not_logged_at_info(caplog):
    import logging

    async def scenario():
        async def handler(ws):
            await ws.send(READY)
            await ws.send(json.dumps({"type": "transcript", "text": "private words"}))
            await ws.wait_closed()

        server, url = await _serve(handler)
        got = []
        client = WebSocketClient(url, api_key="", on_transcript=got.append)
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: got, timeout=5)
        finally:
            await _stop(client, task, server)
        return got

    with caplog.at_level(logging.INFO):
        got = asyncio.run(scenario())
    assert got == ["private words"]
    assert "private words" not in caplog.text


def test_reconnect_now_while_connected_skips_the_backoff():
    """Settings path: reconnect_now() then _close_socket() must reconnect at
    once (no 2 s wait), and leave no stale skip behind."""

    async def scenario():
        handshakes = 0

        async def handler(ws):
            nonlocal handshakes
            handshakes += 1
            await ws.send(READY)
            await ws.wait_closed()

        server, url = await _serve(handler)
        client = WebSocketClient(url, api_key="")
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: client.is_connected and client._reconnect_count == 0)
            client.reconnect_now()
            await client._close_socket()
            again = await _wait_for(lambda: handshakes == 2 and client.is_connected, timeout=1.0)
            skip_left = client._skip_backoff
        finally:
            await _stop(client, task, server)
        return again, skip_left

    again, skip_left = asyncio.run(scenario())
    assert again, "should reconnect immediately after a settings change"
    assert skip_left is False


def test_reconnect_now_abandons_a_connect_using_old_settings():
    """A connect hanging on the old URL must not delay (or win over) the new one."""

    async def scenario():
        async def black_hole(reader, writer):
            await asyncio.sleep(30)  # accept TCP, never answer the handshake

        hole = await asyncio.start_server(black_hole, "127.0.0.1", 0)
        hole_url = f"ws://127.0.0.1:{hole.sockets[0].getsockname()[1]}"

        async def handler(ws):
            await ws.send(READY)
            await ws.wait_closed()

        server, good_url = await _serve(handler)
        client = WebSocketClient(hole_url, api_key="")
        task = asyncio.create_task(client.run(asyncio.Queue()))
        try:
            await _wait_for(lambda: client._connect_task is not None)
            await asyncio.sleep(0.2)  # the handshake is now stuck
            client.server_url = good_url
            client.reconnect_now()
            switched = await _wait_for(lambda: client.is_connected, timeout=2.0)
        finally:
            await _stop(client, task, server)
            hole.close()
        return switched

    assert asyncio.run(scenario())


def test_stop_abandons_an_in_flight_connect():
    async def scenario():
        async def black_hole(reader, writer):
            await asyncio.sleep(30)

        hole = await asyncio.start_server(black_hole, "127.0.0.1", 0)
        url = f"ws://127.0.0.1:{hole.sockets[0].getsockname()[1]}"
        client = WebSocketClient(url, api_key="")
        task = asyncio.create_task(client.run(asyncio.Queue()))
        await _wait_for(lambda: client._connect_task is not None)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await _stop(client, task, timeout=2)
        hole.close()
        return loop.time() - started

    assert asyncio.run(scenario()) < 1.0


def test_busy_refusal_uses_a_short_backoff_cap(caplog):
    import logging

    async def scenario():
        client = WebSocketClient("ws://unused", api_key="")
        client._running = True
        client._wake = asyncio.Event()
        client._reconnect_count = 5
        client._handle_close_code(wsc.CLOSE_ALREADY_CONNECTED)
        waiting = asyncio.create_task(client._backoff())
        await asyncio.sleep(0.05)
        client.stop()
        await waiting
        client._running = True
        client._handle_close_code(None)  # e.g. a network drop: normal cap
        waiting = asyncio.create_task(client._backoff())
        await asyncio.sleep(0.05)
        client.stop()
        await waiting

    with caplog.at_level(logging.INFO, logger="wispr_dragon.client.websocket_client"):
        asyncio.run(scenario())
    assert f"Reconnecting in {wsc._BUSY_MAX_BACKOFF_S} seconds" in caplog.text
    assert f"Reconnecting in {wsc._MAX_BACKOFF_S} seconds" in caplog.text


def test_is_connected_needs_an_open_socket():
    client = WebSocketClient("ws://unused", api_key="")
    client.websocket = object()  # no `open` attribute: not known to be open
    assert client.is_connected is False
    client.websocket = _HangingSocket()
    assert client.is_connected is True
