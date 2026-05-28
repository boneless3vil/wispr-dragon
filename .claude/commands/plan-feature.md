---
description: Plan a feature end-to-end. Architect drafts the design, then the relevant implementer reads it and proposes a task breakdown. No code is written.
---

You are kicking off a new feature: $ARGUMENTS

Do this:

1. Delegate to **architect** with the feature description. Wait for the design memo.
2. Read the memo. Identify which implementer(s) the work touches: server-dev, client-dev, audio-stt — possibly more than one.
3. Delegate to each relevant implementer in parallel with the architect's memo as context. Ask each to return ONLY a task breakdown for their area, not code.
4. Combine the responses into a single ordered task list, with dependencies marked.
5. Show the user the design memo + task list. Ask: "Proceed with implementation?" Do not start coding until they say yes.

Output should be tight enough to fit on one screen. No code in this phase.
