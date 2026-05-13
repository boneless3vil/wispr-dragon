# Wispr_Dragon Build Log

This document tracks all changes made to the Wispr_Dragon application codebase.

## Build History

### Build 2026-05-13: Naming Consistency - Wispr_Dragon

**Branch:** feature/rename-wispr_dragon  
**Commit:** e81aa00  
**Changes:**
- Renamed package from `wispr-dragon` to `wispr_dragon` for consistency
- Updated `pyproject.toml` project name and console script
- Updated `environment.yml` Conda environment name
- Updated config directory from `~/.wispr-dragon` to `~/.wispr_dragon` with backward compatibility fallback
- Updated all documentation files (README, QUICKSTART, SETUP_OPENAI_API, START_HERE, BUILD_LOG, GITHUB_SETUP)
- Updated .gitignore for new config directory
- Updated config path references in `config.py`, `command_mode.py`, `dictionary.py`

**Testing Status:**
- Code changes: ✅ Applied
- Package name: ✅ Updated to wispr_dragon
- Config paths: ✅ Updated with fallback compatibility
- Documentation: ✅ Updated

**Manual Steps Still Required:**
- Rename local directory: `/home/jon/wispr-dragon/` → `/home/jon/wispr_dragon/`
- Recreate Conda environment: `conda env remove -n wispr-dragon && conda env create -f environment.yml`
- Update GitHub repository name (optional): `wispr-dragon` → `wispr_dragon`

**Next Steps:**
- After directory rename, test application with new paths
- Verify Conda environment creation with new name
- Optional: merge back to main when stable

---

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