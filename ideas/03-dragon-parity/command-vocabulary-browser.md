# Command & Vocabulary browser

## Problem

`data/default_commands.yaml` defines built-in commands; users add their own in `~/.wispr_dragon/commands.yaml`. The user dictionary is JSON at `~/.wispr_dragon/user_dictionary.json`. Both are edited by hand — no UI. CLAUDE.md references `ui/macro_editor.py` but the file doesn't exist.

For non-technical users (the Dragon demographic) this is a wall.

## Solution

`wispr_dragon/ui/vocabulary_browser.py` — a tabbed PyQt6 window:

- **Commands tab**: lists triggers + actions; double-click to edit; "Add" button opens a form for trigger, action type (shell, key, macro, system), parameters, description. Validates against the same YAML schema the existing loader expects.
- **Vocabulary tab**: shows user dictionary entries (custom words, corrections, hotwords). Sort by frequency. Right-click "Bump priority" or "Delete." Search/filter box at top.
- **Imports tab**: drag-and-drop a `.docx` or `.txt` of domain text (medical notes, legal templates, code snippets). The system extracts proper nouns and infrequent words, asks the user which to add as hotwords. Dragon calls this "Learn from documents."
- **Test tab**: a "say something" widget that shows what command (if any) the engine would match, and which dictionary entries would apply. Live debugger.

Layout cribbed from Dragon's Vocabulary Editor + Command Browser, but with the search-first / search-everywhere expectations of modern UIs.

## Plumbing

The existing `CommandRegistry.load()` (`modes/command_mode.py:28`) already supports a user path. After save, the browser calls `_registry.load()` to refresh. For the user dictionary, `UserDictionary` (`correction/dictionary.py`) already has add/remove APIs — wrap them.

YAML round-trips need careful preservation of comments and ordering — use `ruamel.yaml` rather than `pyyaml` for the editor's save path.

## Affected files

- New `wispr_dragon/ui/vocabulary_browser.py`.
- `wispr_dragon/ui/tray.py` — menu item "Vocabulary editor…" → open browser.
- `wispr_dragon/modes/command_mode.py` — `CommandRegistry.reload()` method (just an alias for `load()`).
- `pyproject.toml` — add `ruamel.yaml` to `gui` extra.
- New `tests/test_vocabulary_browser.py`.

## Effort

Medium. The form-based command editor is the time sink — validation, action-type-specific field rendering, saving without trashing user comments in the YAML.

## Gotcha

Don't let the editor save a command that conflicts with a built-in trigger silently. Show a "this trigger overrides built-in 'X'" warning, and require explicit confirm.
