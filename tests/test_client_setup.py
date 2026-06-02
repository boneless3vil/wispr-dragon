"""Tests for the client first-run setup: pure helpers + key-export formatting.

Pure-logic tests (no Qt, no display). The Qt SetupDialog itself is tested
separately offscreen once it exists.
"""

from __future__ import annotations

import pytest

from wispr_dragon.client.app import needs_setup, validate_setup
from wispr_dragon.main import format_client_setup


# --- needs_setup ----------------------------------------------------------

def test_needs_setup_true_when_key_empty():
    assert needs_setup({"server_url": "ws://localhost:8765", "api_key": ""}) is True


def test_needs_setup_true_when_url_empty():
    assert needs_setup({"server_url": "", "api_key": "abc"}) is True


def test_needs_setup_true_when_keys_missing():
    assert needs_setup({}) is True


def test_needs_setup_false_when_both_present():
    assert needs_setup({"server_url": "ws://localhost:8765", "api_key": "abc"}) is False


# --- validate_setup -------------------------------------------------------

def test_validate_setup_accepts_ws_and_key():
    ok, msg = validate_setup("ws://192.168.1.10:8765", "deadbeef")
    assert ok is True and msg == ""


def test_validate_setup_accepts_wss():
    ok, _ = validate_setup("wss://host:8765", "k")
    assert ok is True


def test_validate_setup_rejects_blank_key():
    ok, msg = validate_setup("ws://localhost:8765", "   ")
    assert ok is False and "key" in msg.lower()


def test_validate_setup_rejects_http_scheme():
    ok, msg = validate_setup("http://localhost:8765", "k")
    assert ok is False and "ws://" in msg


def test_validate_setup_rejects_garbage_url():
    ok, msg = validate_setup("not a url", "k")
    assert ok is False


def test_validate_setup_trims_whitespace():
    ok, _ = validate_setup("  ws://localhost:8765  ", "  k  ")
    assert ok is True


# --- format_client_setup (--print-key block) ------------------------------

def test_format_client_setup_contains_key_url_and_json():
    out = format_client_setup("abcd1234", "192.168.1.10", 8765, generated=True)
    # Grep-compatible legacy line preserved.
    assert "API Key: abcd1234" in out
    # Server URL built from host+port.
    assert "ws://192.168.1.10:8765" in out
    # Ready-to-paste JSON snippet present.
    assert '"server_url": "ws://192.168.1.10:8765"' in out
    assert '"api_key": "abcd1234"' in out


def test_format_client_setup_generated_note_toggles():
    gen = format_client_setup("k", "h", 8765, generated=True)
    existing = format_client_setup("k", "h", 8765, generated=False)
    assert "saved to server config.yaml" in gen
    assert "saved to server config.yaml" not in existing
