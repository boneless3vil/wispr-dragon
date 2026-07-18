# Hotword prompt templates

## Problem

`EngineConfig.hotwords` and `EngineConfig.initial_prompt` exist and are passed through to engines (see `pipeline_runner.py:133-134`), but most users will leave them empty because they don't know how to write a good one. Whisper's `initial_prompt` is finicky — too generic and you bias toward bad words; too specific and you over-fit.

## Solution

Ship a small library of domain templates the user picks in the settings UI:

```yaml
# data/initial_prompt_templates.yaml
templates:
  general: ""
  medical: |
    The following is a medical note. Common terms include: hypertension,
    diabetes, mg, mcg, BID, TID, PRN, EKG, MRI, CT, IV.
  legal: |
    The following is a legal document. Common terms include: plaintiff,
    defendant, motion, herein, whereas, pursuant, jurisdiction.
  code-python: |
    The following is Python code. Common identifiers include: def, class,
    return, import, async, await, lambda, self, None, True, False.
  code-typescript: ...
  email: |
    The following is an email. Greetings: hi, hello, dear, hey. Closings:
    thanks, regards, best, cheers.
```

Settings UI lets the user pick a template or paste their own; the per-user picked template gets concatenated with the voice profile's adaptive piece (see [voice-profile-adaptive-lm](../04-differentiators/voice-profile-adaptive-lm.md)).

## Effort

Trivial — content is the work, not code.
