# Learn from correction (auto-promote)

## Problem

`UserDictionary.add_correction` exists, and `correction_window.py:135-137` already bumps frequency by 3 if the user checks "always apply." But there's no *passive* learning — if the user types the same correction manually 3 times in a row, the system doesn't notice.

## Solution

When the user corrects a transcribed segment manually (backspace + retype detected, or via the alternates UI from [spoken-alternates-correct-that](spoken-alternates-correct-that.md)):

1. Diff the original transcript against what's now in the focused field (or what the alternates UI returned).
2. If the diff is a single-word substitution and the (original, replacement) pair has been seen 3+ times in the last 30 days, auto-add it to the user dictionary with the auto-apply flag.
3. Surface a tiny toast: "Learning: 'bach' → 'beach' will auto-correct next time. Undo?"

Detecting "user typed a correction" is the tricky bit — requires tracking the post-injection text content vs what's currently in the field. The `WindowsTextInjector` doesn't read; you need OS accessibility APIs (UI Automation on Windows, AXAPI on macOS). Out-of-scope for v1; start with the alternates-UI signal only.

## Effort

Medium if scoped to alternates-UI corrections only. Large if you build the post-injection diff detector.
