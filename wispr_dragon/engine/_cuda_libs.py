"""Preload CUDA-12 runtime libs so CTranslate2 can dlopen them.

faster-whisper's CTranslate2 (4.x) is built against **CUDA 12** and dlopens
``libcublas.so.12`` / ``libcudnn.so.9`` *by soname at first inference* — not at
model-load time, which is why a missing lib surfaces only when you start talking.

When torch is the CUDA-13 build, the CUDA-12 libs aren't on the dynamic-loader
path. We pip-install ``nvidia-cublas-cu12`` + ``nvidia-cudnn-cu12`` and preload
them here with ``RTLD_GLOBAL``, so they're already resident (with global symbols)
when CTranslate2 looks them up. This avoids forcing the user to export
``LD_LIBRARY_PATH`` on every launch and keeps the packaged app self-contained.

Idempotent and defensive: any failure degrades to "let the normal loader try",
so a CPU-only or already-correctly-configured environment is unaffected.
"""

import ctypes
import glob
import logging
import os

logger = logging.getLogger(__name__)

_done = False

# Soname fragments we care about, under each ``nvidia/<pkg>/lib`` dir. cuDNN 9
# ships a dispatcher (libcudnn.so.9) plus sublibs it lazily dlopens; preloading
# them all RTLD_GLOBAL lets the dispatcher resolve them in-process.
_GLOBS = (
    "cuda_nvrtc/lib/libnvrtc.so.12",
    "cublas/lib/libcublasLt.so.12",
    "cublas/lib/libcublas.so.12",
    "cudnn/lib/libcudnn*.so.9",
)


def _candidate_paths() -> list:
    try:
        import nvidia
    except ImportError:
        return []
    # ``nvidia`` is a PEP 420 namespace package (no __init__), so __file__ is
    # None; iterate its __path__ entries instead.
    bases = list(getattr(nvidia, "__path__", []))
    paths: list = []
    for base in bases:
        for pat in _GLOBS:
            paths.extend(sorted(glob.glob(os.path.join(base, pat))))
    return paths


def preload_cuda12_libs() -> None:
    """Best-effort preload of the CUDA-12 cuBLAS/cuDNN libs (idempotent).

    Multi-pass: a lib whose dependency isn't resident yet fails to load, so we
    keep retrying the leftovers until a full pass makes no progress. That
    resolves load order without hardcoding the dependency graph.
    """
    global _done
    if _done:
        return
    _done = True

    pending = _candidate_paths()
    if not pending:
        logger.debug("No nvidia cu12 libs found to preload")
        return

    loaded = 0
    while pending:
        progressed = False
        still: list = []
        for path in pending:
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                loaded += 1
                progressed = True
            except OSError as e:
                last_err = e
                still.append(path)
        pending = still
        if not progressed:
            for path in pending:
                logger.debug("Could not preload %s (%s)", path, last_err)
            break
    logger.debug("Preloaded %d CUDA-12 lib(s) for CTranslate2", loaded)
