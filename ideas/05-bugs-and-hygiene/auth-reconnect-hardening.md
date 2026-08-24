# WebSocket auth-reconnect storm regression test

## Problem

CLAUDE.md says:

> Auth required; reconnect storms on auth failure were fixed once — don't reintroduce.

There's no test specifically for this. A future refactor could silently bring it back, and the only signal would be a user reporting their server got flooded.

## Fix

Add `tests/test_websocket_reconnect.py`:

1. Start the server (or a mock) configured to reject all auth.
2. Start a client.
3. Assert that after `N` consecutive auth failures, the client backs off exponentially (verify by counting connection attempts over a window).
4. Assert that after the backoff cap, attempts cap at a fixed rate.

If the code today doesn't have explicit backoff (`websocket_client.py`), add it. Suggested: `min(2**failures, 300)` seconds, jittered.

## Affected

- `wispr_dragon/client/websocket_client.py` — confirm backoff logic exists.
- New `tests/test_websocket_reconnect.py`.

## Effort

Small.
