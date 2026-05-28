---
description: Pre-commit gate. Runs tests, reviews the diff, summarizes for a commit message. Does not commit or push.
---

Run the ship gate:

1. **test-runner** — run `pytest tests/ -v --tb=short`. If anything fails, stop and report. Do not proceed.
2. **code-reviewer** — review the uncommitted diff. If verdict is "Fix blocking issues first" or "Needs rework", stop and report.
3. If both pass:
   - Summarize the diff in 1–2 sentences.
   - Propose a commit message following the convention `<scope>: <imperative>` (e.g. `client: add Linux text injector via ydotool`).
   - Cross-platform check: if the diff touches `client/`, `ui/`, or `output/`, list which of Linux/macOS/Windows are covered by tests and which need manual verification.
   - Ask the user: "Commit with this message?" If yes, hand off to **git-ops** to stage and commit. Do not push automatically — pushing is a separate step (use `/pr` if a PR is the goal).

This is a gate, not an action — the user always presses the button.
