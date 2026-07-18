# Accuracy regression suite

## Problem

There's no fixed test corpus or WER scoring. Every engine swap, model change, or post-processor tweak is evaluated by "feels right" — which is exactly how Whisper-based projects regress accuracy silently between releases.

## Solution

A small held-out audio corpus (~30 min total) with hand-transcribed gold references, run on every PR:

```
tests/
  accuracy/
    corpus/
      clean_dictation_01.wav    + .txt
      noisy_office_02.wav       + .txt
      code_speak_03.wav         + .txt
      numbers_addresses_04.wav  + .txt
      multispeaker_05.wav       + .txt
    test_wer.py
```

`test_wer.py` runs the configured engine over each clip, computes WER with `jiwer`, and fails if it exceeds a per-clip ceiling stored in `tests/accuracy/baselines.json`. To update the baseline, you have to commit a `baselines.json` change — making accuracy regressions a visible part of every PR diff.

Categorize clips so you can see *which* axis regressed: clean-dictation, noisy-environment, code-speak, numbers/addresses, multi-speaker.

## Affected files

- New `tests/accuracy/` tree.
- `pyproject.toml` — add `jiwer` to `dev` extra.
- `.github/workflows/tests.yml` (or equivalent) — run accuracy job on PRs touching engine/ or correction/.

## Effort

Small once the corpus is recorded. The recording (sourcing diverse voices + hand-transcribing) is the actual cost — budget a day for ~30 min of varied audio.

## Gotcha

Don't include the audio in git directly (large + binary noise on diffs). Stash it in git-lfs or a release-asset URL and download on test run.
