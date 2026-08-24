# NATO spelling mode

## Problem

Even outside spelling mode, users sometimes want to spell something short: a password hint, a license plate, an unusual name. Forcing a full mode switch for two letters is heavy.

## Solution

An inline "spell" trigger that consumes the next N tokens as NATO phonetic letters until a "stop" cue or a non-NATO word:

> "My address is spell alpha bravo charlie one two three end spell main street"
> → "My address is ABC123 main street"

Lives as a small parser hooked into the dictation post-processor. Recognizes:

- NATO words (alpha…zulu).
- Common "say-the-letter" variants ("ay, bee, cee, dee").
- "Number" + digit word.
- Termination on "end spell," "stop," or any non-NATO word (configurable).

Distinct from a full spelling mode because it scopes to a single phrase, not a mode the user has to remember to exit.

## Effort

Small. Mostly a state machine over tokens.
