"""Tests for the client's single-instance lock.

Two clients are actively harmful (they fight over the server's single
connection, the global hotkey, and the mic), so the second must be refused.
"""

import socket

from wispr_dragon.client.app import acquire_single_instance


def _free_port() -> int:
    """Pick an unused port so tests don't collide with a real running client."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_first_instance_acquires_lock():
    port = _free_port()
    lock = acquire_single_instance(port)
    try:
        assert lock is not None
    finally:
        if lock:
            lock.close()


def test_second_instance_is_refused():
    port = _free_port()
    first = acquire_single_instance(port)
    try:
        assert first is not None
        assert acquire_single_instance(port) is None
    finally:
        if first:
            first.close()


def test_lock_is_released_on_close():
    """Closing the socket frees the port, so a later run can start."""
    port = _free_port()
    first = acquire_single_instance(port)
    assert first is not None
    first.close()

    second = acquire_single_instance(port)
    try:
        assert second is not None  # no stale lock left behind
    finally:
        if second:
            second.close()
