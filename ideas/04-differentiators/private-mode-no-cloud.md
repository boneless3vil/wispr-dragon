# Private mode (no cloud)

## Problem

As you add cloud engines (Wispr, OpenAI), LLM features (post-processing, semantic commands), and adaptive learning, the cloud surface area grows. Some users — lawyers, doctors, anyone in compliance-bound roles — can't use any of it. They want one switch that disables every network feature and proves it.

## Solution

`PrivacyConfig.private_mode: bool` in `config.py`. When true:

1. Engine selection skips any backend whose `requires_network` flag is True (`openai-api`, `wispr` cloud).
2. LLM post-processor refuses any non-local backend.
3. Semantic router falls through to fuzzy-match only.
4. Voice profile + corrections stay local (already true), but auto-sync (future feature) is hard-disabled.
5. Tray icon gets a small lock badge.
6. Settings UI shows "Private mode is active — all processing is on-device" banner across every page that touches network.

Audit guarantee: a startup self-check enumerates loaded modules and refuses to start if `private_mode=True` and a cloud engine instance exists. Fail loud; never silently degrade.

## Effort

Small. Mostly a flag honored by a handful of factories + a UI banner. The audit step is what makes it credible to compliance-bound users.
