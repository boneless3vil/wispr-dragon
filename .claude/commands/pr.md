---
description: Open a PR for the current branch. Runs the ship gate first; if it passes, git-ops opens the PR.
---

Open a PR for the current branch:

1. Run the `/ship` gate: test-runner → code-reviewer. If either fails, stop and report.
2. Confirm with the user: "Ready to open the PR?" Show the proposed title and body.
3. Delegate to **git-ops** with the approved title and body. It will:
   - Push the branch if needed.
   - Run `gh pr create --base main --head <branch>`.
   - Return the PR URL.
4. Report the PR URL to the user.

Never open a draft as non-draft or vice versa without asking.
