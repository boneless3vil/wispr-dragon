---
description: Sweep the repo for cruft and propose a cleanup plan. Nothing is deleted or moved without approval.
---

Run a cleanup sweep:

1. Delegate to **cleanup** with no arguments — it will inventory and categorize.
2. Show the user the full proposal (KEEP / MOVE / DELETE / INVESTIGATE).
3. Ask: "Approve the MOVE block? Approve any DELETEs? Anything to keep that's in the move list?"
4. After approval, hand back to **cleanup** with the approved list. It will execute via `git mv` / `git rm` / `.gitignore` edits.
5. Hand off to **git-ops** to stage a single commit per category (`chore: move dev notes to docs/dev-notes/`, `chore: stop tracking scratch docs`, etc.). Do not push or open a PR — that's the user's call.
