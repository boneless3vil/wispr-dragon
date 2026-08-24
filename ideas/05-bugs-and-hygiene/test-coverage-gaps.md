# Test coverage gaps

## Problem

Tests exist for `dictionary`, `config_validation`, `windows_injector`, `engine_factory`, `hotkey`, `server_client_e2e`, `security`, `post_processor`, `gpu_advisor`, `macro_runner`, `command_matching`, `ui_components`. Missing coverage on critical hot paths:

- `audio/vad.py` — VAD state machine, buffer guard, model reset.
- `server/websocket_server.py` — message routing, auth, reconnect.
- `server/pipeline_runner.py` — load/process/unload lifecycle.
- `client/audio_capture.py` — sounddevice integration (mockable).
- `correction/hotwords.py` — initial_prompt builder.

## Fix

One test file per module above. Use `pytest` mocks for sounddevice and torch. The E2E test (`test_server_client_e2e.py`) exists but is slow and broad — unit tests catch regressions earlier and pinpoint blame.

## Effort

Medium — one or two days for a thorough pass. Not urgent unless a regression in one of these modules has already happened.
