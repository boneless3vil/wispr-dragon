# Repo cleanup of scratch docs

## Problem

CLAUDE.md already names the issue:

> The repo accumulated phase-tracking and session-notes files during early development (`SESSION_NOTES_*`, `PHASE_*_SUMMARY`, `PUSH_TO_GITHUB.md`, etc.). These are dev scratch, not product docs.

CLAUDE.md also names the owner: the `cleanup` agent.

## Fix

One sweep:

1. `find . -maxdepth 2 -name 'SESSION_NOTES_*' -o -name 'PHASE_*_SUMMARY*' -o -name 'PUSH_TO_GITHUB.md'` — list candidates.
2. Move anything still load-bearing into `docs/dev-notes/`. Anything obsolete: delete.
3. Add `docs/dev-notes/` to `.gitignore` if it isn't already.
4. Add a CI check that fails the build if a file matching the pattern appears at repo root in a PR diff.

## Affected

- Top-level repo files.
- `.gitignore`.
- Optional: a `pre-commit` hook or CI rule.

## Effort

Trivial. Delegate to `cleanup` agent.
