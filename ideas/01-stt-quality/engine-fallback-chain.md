# Engine fallback chain

## Problem

`engine/__init__.py` picks one engine at startup and sticks with it. When the cloud engine 429s, times out, or the user's network drops, the transcript just fails — there's no graceful degradation.

## Solution

A `FallbackEngine` that wraps a list of `TranscriptionEngine`s and tries them in order, with circuit-breaker semantics so a flapping cloud doesn't add latency to every call.

```python
class FallbackEngine(TranscriptionEngine):
    def __init__(self, engines: list[TranscriptionEngine]):
        self.engines = engines
        self.breakers = {e.name: _Breaker() for e in engines}

    def transcribe(self, audio, **kw):
        last_err = None
        for engine in self.engines:
            if self.breakers[engine.name].is_open():
                continue
            try:
                t0 = time.monotonic()
                result = engine.transcribe(audio, **kw)
                self.breakers[engine.name].record_success(time.monotonic() - t0)
                return result
            except (TimeoutError, ConnectionError, RateLimitError) as e:
                self.breakers[engine.name].record_failure()
                last_err = e
                continue
        raise last_err
```

`_Breaker` opens after N failures in a rolling window, closes after a backoff period (30 s), then half-opens to test recovery. Standard pattern.

Tier order from config: `engine.fallback_chain: ["wispr", "openai-api", "faster-whisper"]`. When `wispr` is unhealthy, fall through to OpenAI; if both are out, fall through to local.

Surface tier transitions in the UI: tray icon adds a small badge ("L" for local fallback) so the user knows their audio isn't going to the cloud.

## Affected files

- `wispr_dragon/engine/__init__.py` — `FallbackEngine` + factory plumbing.
- `wispr_dragon/config.py` — extend `EngineConfig.fallback_chain`.
- `wispr_dragon/ui/tray.py` (when it exists) — badge on tier switch.
- `tests/test_engine_factory.py` — cover breaker behavior.

## Effort

Small.
