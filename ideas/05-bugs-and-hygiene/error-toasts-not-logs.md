# Surface errors to users, not just logs

## Problem

Across the codebase, errors mostly go to `logger.error(...)` and are swallowed:

- `pipeline_runner.py:94` — pipeline load failure returns False silently.
- `pipeline_runner.py:147` — process error returns "" silently.
- `windows_injector.py:148` — SendInput partial delivery only logs.
- `correction_window.py:47` — PyQt6 missing falls back to terminal with no UI signal.

UI-mode users have no idea anything went wrong; they just see no transcript appear.

## Fix

Introduce a single error sink (`ui/app_state.py:AppState.error`, from [mic-state-model](../03-dragon-parity/mic-state-model.md)) that:

1. Logs (current behavior).
2. Emits a Qt signal subscribed by the tray + dictation box → shows a non-modal toast.
3. Adds an entry to an error history viewable from the tray ("Show recent errors…").

Then sweep `logger.error(...)` calls in the user-visible code paths and add a parallel `app_state.error.emit("user-friendly message")`. Keep the technical message in the log; the toast should be short and actionable.

## Effort

Small once `AppState` exists.
