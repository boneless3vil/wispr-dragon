# Platform dispatch refactor

## Problem

`output/text_injector.py` is the wrapper, but per CLAUDE.md the cross-platform branching is implicit (`sys.platform` checks scattered through `client/app.py`). Adding Linux and macOS will multiply that mess.

## Solution

Single factory in `output/text_injector.py`:

```python
def make_injector() -> TextInjector:
    if sys.platform == "win32":
        from wispr_dragon.client.windows_injector import WindowsTextInjector
        return WindowsTextInjector()
    if sys.platform == "darwin":
        from wispr_dragon.client.macos_injector import MacOSTextInjector
        return MacOSTextInjector()
    if sys.platform.startswith("linux"):
        from wispr_dragon.client.linux_injector import make_linux_injector
        return make_linux_injector()
    return NullInjector()
```

`TextInjector` is the existing abstract base — every platform module subclasses it. `NullInjector.inject()` returns False and logs; gives the rest of the pipeline a non-crashing default on unsupported OSes (e.g. BSD).

Same pattern for hotkey registration (`client/hotkey.py`), audio capture (`client/audio_capture.py` is platform-aware already), focus capture (new module per [dictation-box](../03-dragon-parity/dictation-box.md)).

## Affected files

- `wispr_dragon/output/text_injector.py` — central factory.
- `wispr_dragon/client/app.py` — remove platform branches.
- `wispr_dragon/client/hotkey.py` — same factory pattern.
- New `wispr_dragon/client/null_injector.py` (or fold into text_injector.py).
- Tests: `tests/test_text_injector.py` — patch `sys.platform`, verify dispatch.

## Effort

Small. Do this before, or alongside, the Linux/macOS injectors.
