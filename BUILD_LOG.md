# Wispr_Dragon Build Log

This document tracks all changes made to the Wispr_Dragon application codebase.

## Build History

### Build 2026-05-12: AMD GPU Support Implementation

**Branch:** feature/amd-gpu-support  
**Commits:** afae771, 60b1ebe, a1244ac  
**Changes:**
- Added AMD ROCm GPU support alongside existing NVIDIA CUDA support
- Updated EngineConfig to support GPU device options
- Modified faster-whisper and openai-whisper engines to detect and use GPUs
- Set float16 compute type for GPU acceleration
- Added comprehensive GPU setup documentation in README.md
- Verified ROCm PyTorch 2.5.1+rocm6.2 is installed in environment
- Confirmed AMD GPU detection via HIP 6.2.41133
- Fixed engine auto-selection to prefer openai-whisper for AMD GPUs (faster-whisper doesn't support ROCm)
- Updated config to use "cuda" device for both NVIDIA and AMD (PyTorch handles ROCm via CUDA API)

**Testing Status:**
- PyTorch ROCm installation: ✅ Confirmed
- GPU detection: ✅ HIP available
- Config updates: ✅ Applied
- Engine selection: ✅ Fixed for AMD
- Documentation: ✅ Updated

**Current Status:**
- AMD GPU support implemented and committed
- Ready for testing with openai-whisper engine on ROCm
- Config set to use GPU acceleration

**Next Steps (Tomorrow):**
- Test application with AMD GPU acceleration
- Verify transcription performance improvements
- Monitor for any ROCm-specific issues
- Consider UI development or other features