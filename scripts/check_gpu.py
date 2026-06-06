#!/usr/bin/env python3
"""Detect available GPU backend and report capabilities."""



def check_rocm():
    """Check for ROCm availability via PyTorch."""
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024**3)
            # PyTorch uses "cuda" API even for ROCm
            if "gfx" in device_name.lower() or "radeon" in device_name.lower() or "amd" in device_name.lower():
                return {
                    "backend": "rocm",
                    "device": device_name,
                    "vram_gb": round(vram_gb, 1),
                    "torch_version": torch.__version__,
                }
            return {
                "backend": "cuda",
                "device": device_name,
                "vram_gb": round(vram_gb, 1),
                "torch_version": torch.__version__,
            }
    except Exception as e:
        return {"error": str(e)}
    return None


def check_rocm_smi():
    """Check for ROCm via rocm-smi command."""
    import subprocess
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"rocm_smi": result.stdout.strip()}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def check_ctranslate2():
    """Check if CTranslate2 is available and what backends it supports."""
    try:
        import ctranslate2
        return {
            "ctranslate2_version": ctranslate2.__version__,
            "cuda_supported": ctranslate2.get_cuda_device_count() > 0,
        }
    except ImportError:
        return None
    except Exception as e:
        return {"ctranslate2_error": str(e)}


def main():
    print("=" * 60)
    print("Wispr-Dragon GPU Detection")
    print("=" * 60)

    # Check PyTorch GPU
    print("\n--- PyTorch GPU ---")
    gpu_info = check_rocm()
    if gpu_info and "error" not in gpu_info:
        print(f"  Backend:  {gpu_info['backend']}")
        print(f"  Device:   {gpu_info['device']}")
        print(f"  VRAM:     {gpu_info['vram_gb']} GB")
        print(f"  PyTorch:  {gpu_info['torch_version']}")
    elif gpu_info and "error" in gpu_info:
        print(f"  Error: {gpu_info['error']}")
    else:
        print("  No GPU detected via PyTorch")

    # Check rocm-smi
    print("\n--- ROCm SMI ---")
    rocm_info = check_rocm_smi()
    if rocm_info:
        print(f"  {rocm_info.get('rocm_smi', 'Available')}")
    else:
        print("  Not available")

    # Check CTranslate2
    print("\n--- CTranslate2 ---")
    ct2_info = check_ctranslate2()
    if ct2_info and "ctranslate2_version" in ct2_info:
        print(f"  Version:      {ct2_info['ctranslate2_version']}")
        print(f"  CUDA support: {ct2_info['cuda_supported']}")
    elif ct2_info and "ctranslate2_error" in ct2_info:
        print(f"  Error: {ct2_info['ctranslate2_error']}")
    else:
        print("  Not installed")

    # Recommendation
    print("\n--- Recommendation ---")
    if gpu_info and "error" not in gpu_info:
        backend = gpu_info["backend"]
        if backend == "rocm":
            print("  Use openai-whisper (PyTorch) for ROCm GPU acceleration")
            print("  faster-whisper may not support ROCm; test with caution")
        else:
            print("  Use faster-whisper for best CUDA performance")
        print(f"  Suggested model: large-v3 ({gpu_info['vram_gb']} GB VRAM available)")
    else:
        print("  No GPU detected — using CPU mode")
        print("  Suggested model: small.en or medium.en (INT8)")
        print("  Install PyTorch with ROCm: pip install torch --index-url https://download.pytorch.org/whl/rocm6.2")

    print()


if __name__ == "__main__":
    main()
