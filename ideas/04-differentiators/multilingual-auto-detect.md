# Multilingual auto-detect

## Problem

`EngineConfig.language = "en"` by default. Whisper supports 99 languages and auto-detects, but the config forces a single one. Bilingual users (or anyone who code-switches) get gibberish for the other half.

## Solution

`EngineConfig.language = "auto"` as an allowed value. When set, the faster-whisper backend gets `language=None`, which triggers Whisper's built-in language detection per segment.

Two UX choices:

- **Per-utterance detection** (default): Whisper detects on each segment. Best for code-switchers.
- **Sticky after first detect**: Once detected, lock for the session. Best when audio is one language but the user doesn't know which model variant to load.

UI: "Language: English / Spanish / … / Auto (detect)" dropdown.

## Effort

Trivial — Whisper does the work. Few hours including the dropdown and tests.
