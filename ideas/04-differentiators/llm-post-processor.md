# LLM post-processor

## Problem

`correction/post_processor.py` does mechanical fixups: applies the user dictionary, fuzzy matches, capitalizes sentences, handles spoken punctuation ("comma" → ","). This is fine. It's also exactly what Dragon does, and it's *not* what makes modern dictation feel magic.

Wispr Flow's killer feature is that you can speak in disfluent stream-of-consciousness ("um, so, the thing is uh I want to like, talk about how we should maybe ship the feature on tuesday or maybe wednesday") and get back clean prose ("We should ship the feature on Tuesday or Wednesday."). It does this with a small LLM running over the raw transcript.

Whisper alone doesn't do this. Wispr cloud might. Either way, owning the post-processing layer means we can layer this on top of *any* engine.

## Solution

New `wispr_dragon/correction/llm_processor.py` — an optional pass after `post_processor.py`. Three tiers:

### Tier 1: Format only (default on)

Cheap, local. Use a small instruction-tuned model (gemma-2b-it, Qwen2-1.5B-instruct, phi-3-mini) via `llama-cpp-python` or `transformers`. Prompt:

> Clean up this dictated text. Remove filler words ("um," "uh," "like" used as filler). Fix obvious disfluencies. **Do not change the meaning, add information, or alter style.** Return only the cleaned text.
>
> Input: `{transcript}`

Latency budget: <200 ms for a typical 1–2 sentence segment on CPU with a 2B model in int4. If higher, this becomes a UX problem.

### Tier 2: Style adjustments (opt-in)

Same model, different prompts the user picks from a dropdown in the dictation box footer:

- "Casual" (default — light cleanup only)
- "Professional" (clean grammar, full sentences)
- "Email" (greeting/sign-off awareness)
- "Code comment" (terse, imperative)
- "Bulleted" (turn lists-as-prose into actual lists)

### Tier 3: Semantic transforms (opt-in, cloud-backed)

For "rewrite this paragraph," "make this shorter," etc. — punt to [semantic-commands](semantic-commands.md). Different flow.

### Plumbing

```python
class LLMProcessor:
    def __init__(self, config: LLMProcessorConfig):
        self.enabled = config.enabled
        self.model = None
        self.style = config.style  # "casual" by default

    def load(self):
        if not self.enabled:
            return
        from llama_cpp import Llama
        self.model = Llama(
            model_path=config.model_path,
            n_ctx=2048, n_threads=4, verbose=False,
        )

    def process(self, text: str, mode: str = "dictation") -> str:
        if not self.enabled or not self.model or mode != "dictation":
            return text
        prompt = _build_prompt(text, self.style)
        out = self.model(prompt, max_tokens=len(text.split()) * 2, stop=["\n\n"])
        cleaned = out["choices"][0]["text"].strip()
        # Sanity check: if the model returned something wildly different
        # in length, fall back to the original (it likely hallucinated).
        if _diff_too_wild(text, cleaned):
            return text
        return cleaned
```

Wire in `pipeline_runner.process()` after `post_processor.process()` (line 142). Make it conditional on `mode == DICTATION` — never run in command mode (command matching breaks if "open browser" becomes "Open the browser, please.").

## Config

New `LLMProcessorConfig` in `config.py`:

```python
@dataclass
class LLMProcessorConfig:
    enabled: bool = False  # opt-in initially; flip to True once latency is proven
    backend: str = "llama-cpp"  # "llama-cpp", "openai-api", "anthropic-api"
    model_path: str = ""  # local gguf path; auto-download default model on first run
    style: str = "casual"  # casual | professional | email | code | bulleted
    max_latency_ms: int = 250  # bail out if model exceeds this
    confidence_threshold: float = 0.7  # below this STT confidence, skip LLM
```

## Affected files

- New `wispr_dragon/correction/llm_processor.py`.
- `wispr_dragon/config.py` — `LLMProcessorConfig`.
- `wispr_dragon/server/pipeline_runner.py` — load + invoke.
- `pyproject.toml` — `llm-local` extra with `llama-cpp-python`.
- New `tests/test_llm_processor.py` — mock the model.
- Settings UI — toggle, style picker, "download model" button.
- Documentation — model recommendations by hardware.

## Effort

Medium. The plumbing is small. The work is (a) picking a good default model and prompt, (b) latency testing, (c) writing the "fallback to original if hallucination" guard well enough that it doesn't bite users.

## Gotchas

- **Hallucinations are the killer risk.** The model must not add information. The prompt + a length-diff sanity check + a token-level diff check that flags new proper nouns are all worth doing.
- **Mode awareness.** Never run on command-mode utterances. The pipeline already exposes mode (`mode_mgr.mode == Mode.DICTATION` at `pipeline_runner.py:141`) — gate on this.
- **GPU contention with STT.** If both run on GPU, finals get slower. Prefer CPU for the LLM tier-1 path; a 2B model in int4 at 4-thread CPU is comfortably <200 ms.
- **Privacy.** LLM tier 1 is fully local. Tier 2 should stay local. Tier 3 (cloud) needs the [private-mode-no-cloud](private-mode-no-cloud.md) hard switch to disable it cleanly.
