# Wispr Dragon Release & Distribution Guide

## Overview

There are **three ways** to distribute Wispr Dragon:

1. **PyPI Release** (easiest, most user-friendly) ⭐ **START HERE**
2. **Standalone Executable** (Windows .exe, Linux binary)
3. **Installer Package** (Windows MSI, Linux .deb)

---

## Option 1: PyPI Release 🐍

This is the **recommended starting point**. Users install with `pip install wispr_dragon`.

### Step 1: Build the Package Locally

```bash
# Install build tools
pip install build twine

# Build wheel + source distribution
python -m build

# This creates:
# - dist/wispr_dragon-1.0.0.tar.gz (source)
# - dist/wispr_dragon-1.0.0-py3-none-any.whl (wheel)
```

### Step 2: Test Installation Locally

```bash
# Create a clean virtual environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate

# Test installation from local wheel
pip install dist/wispr_dragon-1.0.0-py3-none-any.whl

# Test CLI
wispr_dragon --help
wispr_dragon --ui  # Should error gracefully if PyQt6 not installed

# Clean up
deactivate
rm -rf test_env
```

### Step 3: Create PyPI Account

1. Visit https://pypi.org/account/register/
2. Create account with strong password
3. Enable two-factor authentication (TOTP)
4. Create API token at https://pypi.org/manage/account/#api-tokens

### Step 4: Configure Credentials

**Option A: Use API Token (Recommended)**
```bash
# Create ~/.pypirc (on Windows: %APPDATA%\pypi\.pypirc)
[distutils]
index-servers =
    pypi

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-AgEIcHlwaS5vcmc...  # Your API token
```

**Option B: Use GitHub Actions (Secure, Automated)**
See "Automating PyPI Releases" section below.

### Step 5: Upload to PyPI

```bash
# Upload with twine (recommended)
twine upload dist/wispr_dragon-1.0.0*

# Or with setuptools (legacy)
python -m twine upload dist/*

# Verify at https://pypi.org/project/wispr_dragon/
```

### Step 6: Users Install

```bash
pip install wispr_dragon
pip install wispr_dragon[gui]
wispr_dragon --ui
```

---

## Option 2: Standalone Executables 🖥️

Create a single `.exe` for Windows or binary for Linux using **PyInstaller**.

### Prerequisites

```bash
pip install pyinstaller
```

### Build for Windows

```bash
# Create spec file with optimizations
pyinstaller \
  --onefile \
  --windowed \
  --name wispr_dragon \
  --icon icon.ico \
  --hidden-import=faster_whisper \
  --hidden-import=sounddevice \
  --hidden-import=silero_vad \
  --hidden-import=PyQt6 \
  wispr_dragon/__main__.py

# Output: dist/wispr_dragon.exe (~200-300 MB depending on ML models)
```

### Build for Linux

```bash
pyinstaller \
  --onefile \
  --name wispr_dragon \
  --hidden-import=faster_whisper \
  --hidden-import=sounddevice \
  --hidden-import=silero_vad \
  --hidden-import=PyQt6 \
  wispr_dragon/__main__.py

# Output: dist/wispr_dragon (~200-300 MB)
```

### Known Issues with PyInstaller

**Problem:** Whisper models are ~500+ MB and slow to bundle
**Solution:** Download models separately in first run:
```python
# wispr_dragon/engine/faster_whisper_engine.py
if not model_cache_exists(model_size):
    logger.info("Downloading model on first run (~600 MB)...")
    model.load_model(model_size)
```

**Problem:** sounddevice may not work in bundled .exe
**Solution:** Test thoroughly on target systems before release

### Distribution

```bash
# Windows: Create installer with NSIS (next section)
# Linux: Distribute as standalone binary or .deb (next section)

# Checksum for integrity
sha256sum dist/wispr_dragon.exe > wispr_dragon-1.0.0.sha256
```

---

## Option 3: Installer Packages 📦

### Windows: NSIS Installer

**Step 1: Install NSIS**
- Download from https://nsis.sourceforge.io/download

**Step 2: Create .nsi Script**

```nsis
; wispr_dragon.nsi
!include "MUI2.nsh"

Name "Wispr Dragon 1.0.0"
OutFile "wispr_dragon-1.0.0-installer.exe"
InstallDir "$PROGRAMFILES\Wispr Dragon"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  
  ; Copy executable
  File "dist\wispr_dragon.exe"
  
  ; Create shortcuts
  CreateDirectory "$SMPROGRAMS\Wispr Dragon"
  CreateShortCut "$SMPROGRAMS\Wispr Dragon\Wispr Dragon.lnk" "$INSTDIR\wispr_dragon.exe"
  CreateShortCut "$DESKTOP\Wispr Dragon.lnk" "$INSTDIR\wispr_dragon.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\wispr_dragon.exe"
  Delete "$SMPROGRAMS\Wispr Dragon\Wispr Dragon.lnk"
  Delete "$DESKTOP\Wispr Dragon.lnk"
  RMDir "$SMPROGRAMS\Wispr Dragon"
  RMDir "$INSTDIR"
SectionEnd
```

**Step 3: Build**
```bash
makensis wispr_dragon.nsi
# Output: wispr_dragon-1.0.0-installer.exe
```

### Linux: Debian Package (.deb)

**Step 1: Install stdeb**
```bash
pip install stdeb
```

**Step 2: Build**
```bash
python -m stdeb.command bdist_deb
# Output: deb_dist/wispr-dragon_1.0.0-1_all.deb
```

**Step 3: Install Locally**
```bash
sudo apt install ./deb_dist/wispr-dragon_1.0.0-1_all.deb
wispr_dragon --ui
```

---

## Automating PyPI Releases with GitHub Actions 🤖

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'  # Triggers on tags like v1.0.0

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # OIDC trusted publishing

    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install build tools
        run: pip install build
      
      - name: Build package
        run: python -m build
      
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

**Usage:**
```bash
# Tag and push to trigger release
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions automatically builds and uploads to PyPI
```

---

## Release Checklist ✅

Before releasing:

- [ ] Update version in `pyproject.toml` (e.g., 0.1.0 → 1.0.0)
- [ ] Update `CHANGELOG.md` with new features/fixes
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Build package locally: `python -m build`
- [ ] Test installation in clean environment
- [ ] Update README.md with any new instructions
- [ ] Create GitHub release with release notes
- [ ] For PyPI: verify account & API token work
- [ ] For executables: test on target OS (Windows, Linux)

---

## Version Numbering (Semantic Versioning)

Format: `MAJOR.MINOR.PATCH` (e.g., 1.0.0)

- **MAJOR** (1.0.0 → 2.0.0) — Breaking changes
- **MINOR** (1.0.0 → 1.1.0) — New features, backward compatible
- **PATCH** (1.0.0 → 1.0.1) — Bug fixes

### Bumping Version

```bash
# Update pyproject.toml
version = "1.1.0"

# Commit and tag
git add pyproject.toml
git commit -m "Bump version to 1.1.0"
git tag v1.1.0
git push origin main --tags
```

---

## Distribution Channels Summary

| Channel | Command | Users | Pros | Cons |
|---------|---------|-------|------|------|
| **PyPI** | `pip install wispr_dragon` | All Python users | Universal, simple, pip ecosystem | Requires Python 3.11+ |
| **Windows .exe** | Double-click installer | Non-technical Windows users | No Python required | Large file, slow PyInstaller builds |
| **Linux .deb** | `apt install wispr-dragon` | Debian/Ubuntu users | System integration, package manager | Only for Linux distros |
| **GitHub Releases** | Download .exe/.deb | Developers | Easy access, version history | No auto-update |

---

## Recommended Release Strategy (For You)

### Phase 1: MVP Release (Now)
1. ✅ Update `pyproject.toml` with correct version (already done!)
2. ✅ Update `README.md` with installation steps (already done!)
3. Build and test locally: `python -m build`
4. Upload to PyPI: `twine upload dist/*`
5. Announce: "Wispr Dragon v1.0.0 now on PyPI!"

### Phase 2: Enhanced Distribution (Later)
1. Create PyInstaller .exe for Windows users
2. Create NSIS installer for one-click installation
3. Set up GitHub Actions for automated PyPI releases

### Phase 3: Desktop App (Future)
1. Create system tray installer for Windows Start Menu
2. Auto-update mechanism
3. Analytics/telemetry (optional)

---

## Troubleshooting

**Issue:** `twine upload` fails with 403 Forbidden
- **Fix:** Verify API token in `.pypirc`, regenerate if needed

**Issue:** `pip install wispr_dragon` fails
- **Fix:** Check PyPI page for "Project description" — make sure README renders correctly

**Issue:** PyInstaller .exe doesn't work on user machines
- **Fix:** Bundle with smaller models, or download on first run; test on clean machines

**Issue:** GitHub Actions publish fails
- **Fix:** Verify OIDC token configuration in PyPI account settings

---

## References

- [Python Packaging Guide](https://packaging.python.org/)
- [PyInstaller Documentation](https://pyinstaller.org/)
- [PyPI Help](https://pypi.org/help/)
- [Semantic Versioning](https://semver.org/)
- [NSIS Tutorial](https://nsis.sourceforge.io/Docs/Chapter2.html)

---

**Ready to release?** Start with [Option 1: PyPI Release](#option-1-pypi-release) — takes ~15 minutes! 🚀
