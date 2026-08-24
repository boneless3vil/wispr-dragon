# Semantic commands

## Problem

`modes/command_mode.py` does fuzzy string matching against `commands.yaml` triggers. This works for "open browser" → `{"action": "shell", "cmd": "firefox"}` because the user can be trained to use the exact trigger. It does *not* work for:

- "Fix that sentence."
- "Make this more polite."
- "Turn this into a bulleted list."
- "Translate the last paragraph to Spanish."
- "Email this to my manager."

These are commands whose *meaning* must be understood, not whose *form* is matched. Dragon never solved them. We can.

## Solution

A second matcher layered after the fuzzy match: if no command matches above the threshold *and* the utterance starts with a verb-like trigger ("fix," "make," "turn," "rewrite," "email," "find," "go to"), route to an LLM-backed semantic router.

### Architecture

```
transcript ──▶ exact match ──▶ fuzzy match ──▶ semantic router ──▶ dictation
              (commands.yaml)  (commands.yaml)  (LLM tool-call)     (fallback)
```

### The semantic router

A small LLM with a fixed set of *tools* it can pick from. Same model as the LLM post-processor (or a different one if needed).

```python
SEMANTIC_TOOLS = [
    {
        "name": "rewrite_text",
        "description": "Rewrite the last dictated text with a transformation.",
        "params": {"transform": "shorter | longer | formal | casual | bulleted | grammar",
                   "target": "last_sentence | last_paragraph | selection"},
    },
    {
        "name": "translate",
        "description": "Translate the last dictated text to another language.",
        "params": {"language": "string", "target": "last_sentence | last_paragraph | selection"},
    },
    {
        "name": "open_app_or_url",
        "description": "Open an application or URL.",
        "params": {"what": "string"},
    },
    {
        "name": "search",
        "description": "Search the web or a local search index.",
        "params": {"query": "string", "where": "web | files | mail"},
    },
    {
        "name": "no_match",
        "description": "This utterance is not a command; treat as dictation.",
        "params": {},
    },
]
```

The model is given the utterance + the tool list, and returns a JSON tool call. The router dispatches: rewrite goes back through `llm_processor` with a stronger prompt; translate similarly; open/search delegate to existing macro actions or platform shells.

### Confirmation for destructive actions

Anything that modifies user-visible text or opens a URL/app should re-use the existing `confirm_command.py` UI (an "are you sure?" dialog) by default, with a per-command "skip confirmation" preference. This protects against the "I said 'fix that paragraph' meaning the one I was writing, not the meeting notes from earlier" class of bug.

### Latency

Routing budget: <300 ms. If the LLM takes longer, the router should bail and fall through to dictation, with a toast: "Couldn't classify — typed as dictation. Press [hotkey] to undo."

## Affected files

- New `wispr_dragon/modes/semantic_router.py`.
- `wispr_dragon/server/pipeline_runner.py` — call semantic router when fuzzy match fails AND mode allows commands (i.e. dictation mode with semantic-commands enabled, or explicit command mode).
- `wispr_dragon/correction/llm_processor.py` — share the underlying model.
- New `wispr_dragon/macros/builtin_actions.py` — implementations for rewrite/translate/open/search.
- `wispr_dragon/config.py` — `SemanticCommandsConfig` with enabled flag and per-tool allow-list.
- `wispr_dragon/ui/confirm_command.py` — already exists; just feed it the parsed tool call.
- Tests: cover the matcher fall-through, the JSON parse failure, the confirmation gate.

## Effort

Large. Most of the cost is in the per-tool implementations (rewrite, translate, search, open) — the router itself is a few hundred lines. Tackle in order: rewrite (re-uses [llm-post-processor](llm-post-processor.md)) → open/search → translate.

## Gotchas

- **False-positive trigger detection.** A user dictating "fix the typo here" into a doc shouldn't have it interpreted as a command. Mitigations: (a) require an explicit prefix like "Dragon, fix the typo," (b) require the user to be in command mode for semantic routing, (c) use confidence scores from the LLM and bail aggressively. Option (a) is the cleanest — borrow Dragon's "wake word."
- **Privacy of the LLM.** The LLM sees raw transcripts including potentially sensitive content. Default to local-only. Cloud routers must be explicit opt-in and respect [private-mode-no-cloud](private-mode-no-cloud.md).
- **Undo.** Every semantic action must be undoable. Track an undo stack of (action, target, before-state) so the user can say "undo that" or hit a hotkey.
- **Tool brittleness.** LLM tool-calling on small models is unreliable. Use a schema validator (Pydantic) on every return and fall back to dictation on parse failure. Don't trust the model — verify.
