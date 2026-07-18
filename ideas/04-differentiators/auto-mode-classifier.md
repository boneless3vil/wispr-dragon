# Auto mode classifier

## Problem

Dragon (and the current wispr_dragon design) forces the user to say "command mode" / "dictation mode" / "spelling mode" explicitly. This is friction. Modern users want to just talk; the system should figure out whether "open browser" is a command or part of an essay about browsers.

## Solution

A tiny intent classifier (small LLM or fine-tuned distilbert) that runs over each segment in dictation mode and outputs one of: `dictation`, `command`, `correction`, `mode_switch`.

Heuristics first (cheap, then LLM only on ambiguity):

- Starts with "open / go to / launch / find / search / play / send / email / fix / make / turn / rewrite" → likely command.
- Starts with "correct that / scratch that / undo / select / pick / choose" → correction.
- Starts with "spelling mode / numbers mode / command mode / dictation mode" → mode_switch.
- Otherwise default dictation.

LLM second-pass only when confidence < threshold. Required only because the heuristic must be conservative (false-positive commands inject nothing; false-positive dictation is recoverable).

## Effort

Medium. The hard part isn't the model — it's the UX for when the classifier is wrong. Need a one-key "no, this was dictation" undo.

## Gotcha

This *replaces* the explicit-mode UX; it doesn't add to it. If both exist, users get confused. Make this an opt-in toggle in settings: "Auto-classify commands vs dictation."
