"""Tests for the GPU detector / model recommender.

``recommend_model`` is pure given a GpuInfo, so it's tested by feeding
constructed GpuInfo values. ``detect_gpu`` depends on the host, so it's only
checked for a well-formed result.
"""

from wispr_dragon.engine.gpu_advisor import (
    GpuInfo,
    ModelRecommendation,
    detect_gpu,
    recommend_model,
)

# Models small enough to be recommended for real-time dictation.
REALTIME_MODELS = {"tiny.en", "base.en", "small.en", "medium.en"}


def _gpu(free, total=16.0, name="Test GPU"):
    """Build an available-GPU GpuInfo with the given free/total VRAM (GB)."""
    return GpuInfo(
        available=True, name=name, backend="cuda",
        total_vram_gb=total, free_vram_gb=free,
    )


CPU = GpuInfo(available=False, name="CPU", backend="cpu",
              total_vram_gb=0.0, free_vram_gb=0.0)


def test_cpu_recommends_base():
    rec = recommend_model(CPU)
    assert rec.model == "base.en"
    assert "CPU" in rec.reason


def test_high_vram_recommends_medium():
    assert recommend_model(_gpu(free=14.0)).model == "medium.en"


def test_six_gb_free_is_the_medium_threshold():
    # Default _gpu() has total=16 GB, so the total gate is satisfied.
    assert recommend_model(_gpu(free=6.0)).model == "medium.en"
    assert recommend_model(_gpu(free=5.9)).model == "small.en"


def test_small_card_does_not_get_medium_even_with_free_vram():
    # An 8 GB laptop GPU can momentarily show 6+ GB free but thrashes on
    # medium.en under WSL2 — the total-VRAM gate must keep it on small.en.
    rec = recommend_model(_gpu(free=6.9, total=8.0))
    assert rec.model == "small.en"
    assert "8 GB" in rec.reason


def test_mid_vram_recommends_small():
    assert recommend_model(_gpu(free=4.0)).model == "small.en"


def test_low_vram_recommends_base():
    assert recommend_model(_gpu(free=2.0)).model == "base.en"


def test_tiny_vram_recommends_tiny():
    assert recommend_model(_gpu(free=0.8)).model == "tiny.en"


def test_large_v3_is_never_auto_recommended():
    # Even on a huge card, large-v3 is too slow for real-time dictation.
    for free in (8.0, 16.0, 24.0, 48.0):
        assert recommend_model(_gpu(free=free, total=free)).model != "large-v3"


def test_recommendation_is_always_a_realtime_model():
    for free in (0.3, 1.0, 1.5, 2.5, 4.0, 6.0, 12.0, 40.0):
        assert recommend_model(_gpu(free=free)).model in REALTIME_MODELS


def test_reason_explains_free_vram_when_card_is_busy():
    # 16 GB card with only 4 GB free -> 12 GB in use -> reason should explain
    # that free (not total) VRAM drove the pick.
    rec = recommend_model(_gpu(free=4.0, total=16.0))
    assert "free VRAM" in rec.reason or "shared" in rec.reason


def test_reason_omits_busy_note_when_card_is_idle():
    # 16 GB card with 15 GB free -> nothing notable about other usage.
    rec = recommend_model(_gpu(free=15.0, total=16.0))
    assert "shared" not in rec.reason and "Other processes" not in rec.reason


def test_recommend_model_keeps_the_gpu_it_was_given():
    gpu = _gpu(free=7.0, name="RTX Fictional")
    rec = recommend_model(gpu)
    assert isinstance(rec, ModelRecommendation)
    assert rec.gpu is gpu


def test_detect_gpu_returns_wellformed_gpuinfo():
    info = detect_gpu()
    assert isinstance(info, GpuInfo)
    assert info.backend in ("cuda", "rocm", "cpu")
    assert info.total_vram_gb >= 0.0
    assert info.free_vram_gb >= 0.0
    # A CPU result must not claim VRAM; a GPU result must report a name.
    if not info.available:
        assert info.backend == "cpu"
