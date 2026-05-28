"""GPU detection and Whisper model recommendation.

Recommends a model size from *free* GPU VRAM rather than total — under WSL2 the
GPU is shared with Windows, so free VRAM is the honest signal for what will
actually run without thrashing. ``large-v3`` is never auto-recommended: it is
accurate but too slow for low-latency dictation (users can still pick it).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GpuInfo:
    """Detected GPU state. ``available`` is False for a CPU-only machine."""

    available: bool
    name: str
    backend: str          # "cuda", "rocm", or "cpu"
    total_vram_gb: float
    free_vram_gb: float


@dataclass
class ModelRecommendation:
    """A recommended model plus the reasoning behind it."""

    model: str
    reason: str
    gpu: GpuInfo


def _is_wsl() -> bool:
    """True when running under WSL (the GPU is shared with Windows)."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _looks_like_amd(name: str) -> bool:
    """Heuristic — PyTorch reports ROCm devices through the CUDA API."""
    low = name.lower()
    return any(tag in low for tag in ("gfx", "radeon", "amd", "instinct"))


def detect_gpu() -> GpuInfo:
    """Detect the active GPU and its VRAM. Always returns a GpuInfo.

    Any failure (no torch, no driver, no GPU) falls back to a CPU GpuInfo
    rather than raising — callers can treat the result as advisory.
    """
    cpu = GpuInfo(
        available=False, name="CPU", backend="cpu",
        total_vram_gb=0.0, free_vram_gb=0.0,
    )
    try:
        import torch
    except ImportError:
        logger.debug("torch not installed — assuming CPU")
        return cpu

    try:
        if not torch.cuda.is_available():
            return cpu
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        total = props.total_memory / (1024 ** 3)
        try:
            free_bytes, _ = torch.cuda.mem_get_info(0)
            free = free_bytes / (1024 ** 3)
        except Exception:
            # Older torch / driver without mem_get_info — fall back to total.
            free = total
        backend = "rocm" if _looks_like_amd(name) else "cuda"
        return GpuInfo(
            available=True, name=name, backend=backend,
            total_vram_gb=round(total, 1), free_vram_gb=round(free, 1),
        )
    except Exception as e:  # detection must never break the caller
        logger.warning("GPU detection failed (%s) — assuming CPU", e)
        return cpu


def recommend_model(gpu: GpuInfo | None = None) -> ModelRecommendation:
    """Recommend a Whisper model for real-time dictation.

    Args:
        gpu: Pre-detected GpuInfo. If None, :func:`detect_gpu` is called.

    Returns:
        A ModelRecommendation whose ``model`` is always one of the small
        real-time-friendly sizes (tiny/base/small/medium ``.en``).
    """
    if gpu is None:
        gpu = detect_gpu()

    if not gpu.available:
        return ModelRecommendation(
            model="base.en",
            reason="No CUDA GPU detected — running on CPU. base.en keeps "
                   "latency tolerable; larger models are slow without a GPU.",
            gpu=gpu,
        )

    free = gpu.free_vram_gb
    total = gpu.total_vram_gb

    # medium.en needs both a momentary ~6 GB free *and* a card large enough to
    # hold that headroom under load. An 8 GB laptop GPU shared with Windows
    # reports 6+ GB free yet thrashes on medium.en in practice — hence the
    # 12 GB total gate, not free VRAM alone.
    if free >= 6.0 and total >= 12.0:
        model = "medium.en"
        note = "the accuracy/latency sweet spot for dictation, with headroom to spare."
    elif free >= 2.5:
        model = "small.en"
        if total < 12.0:
            note = (f"medium.en wants a larger card than this {total:.0f} GB GPU "
                    "to hold its headroom under load.")
        else:
            note = "medium.en would need more free VRAM — close other GPU apps and re-check."
    elif free >= 1.5:
        model = "base.en"
        note = "a safe fit for this VRAM level; larger models would be tight."
    else:
        model = "tiny.en"
        note = "the only comfortable fit in this little free VRAM."

    reason = (
        f"{free:.1f} GB free of {total:.0f} GB on {gpu.name}. "
        f"Recommending {model} — {note}"
    )
    # When much of the card is already in use, explain why *free* (not total)
    # VRAM drove the pick — this is the common WSL2 case.
    if gpu.total_vram_gb - free >= 3.0:
        if _is_wsl():
            reason += (" Under WSL2 the GPU is shared with Windows, so this "
                       "tracks free VRAM, not the card's total.")
        else:
            reason += " Other processes are using the GPU, so free VRAM drove this."

    return ModelRecommendation(model=model, reason=reason, gpu=gpu)
