# Quick Start: Release Wispr Dragon in 15 Minutes ⚡

## TL;DR — The Simplest Path

You already have everything set up! Just do this:

### Step 1: Install Build Tools (1 min)
```bash
pip install build twine
```

### Step 2: Build the Package (2 min)
```bash
cd ~/wispr_dragon
python -m build
```

You'll see:
```
dist/wispr_dragon-1.0.0.tar.gz
dist/wispr_dragon-1.0.0-py3-none-any.whl
```

### Step 3: Test It Works (3 min)
```bash
# Create clean test environment
python -m venv test_env
source test_env/bin/activate

# Test the wheel
pip install dist/wispr_dragon-1.0.0-py3-none-any.whl

# Verify
wispr_dragon --help
wispr_dragon --ui --help

# Clean up
deactivate
rm -rf test_env
```

### Step 4: Upload to PyPI (5 min)

**First time only:**
1. Go to https://pypi.org/account/register/
2. Create account
3. Add API token at https://pypi.org/manage/account/
4. Create file `~/.pypirc`:
   ```
   [distutils]
   index-servers = pypi
   
   [pypi]
   repository = https://upload.pypi.org/legacy/
   username = __token__
   password = pypi-Ag...YOUR_TOKEN...
   ```

**Every release:**
```bash
twine upload dist/wispr_dragon-1.0.0*
```

### Step 5: Verify on PyPI (1 min)
Visit: https://pypi.org/project/wispr_dragon/

### Step 6: Users Install (2 min)
```bash
pip install wispr_dragon
pip install wispr_dragon[gui]
wispr_dragon --ui
```

**Done!** 🎉

---

## What You Just Did

| File | What It Does |
|------|-------------|
| `dist/wispr_dragon-1.0.0.tar.gz` | Source code distribution |
| `dist/wispr_dragon-1.0.0-py3-none-any.whl` | Pre-built package (faster install) |
| PyPI entry | Cloud repository for `pip install` |

Users now get Wispr Dragon without needing to clone your GitHub repo!

---

## Next Steps (Optional)

### Want a Windows Installer (.exe)?
See [RELEASE.md → Option 2: Standalone Executables](RELEASE.md#option-2-standalone-executables-)

### Want GitHub to Auto-Upload?
See [RELEASE.md → Automating PyPI Releases](RELEASE.md#automating-pypi-releases-with-github-actions-)

### Want a System Installer (.msi for Windows)?
See [RELEASE.md → Option 3: Installer Packages](RELEASE.md#option-3-installer-packages-)

---

## Troubleshooting

### Build fails: "No module named build"
```bash
pip install --upgrade build
```

### Upload fails: "Invalid token"
- Regenerate API token at https://pypi.org/manage/account/
- Update `~/.pypirc` with new token

### `twine upload` says "Already exists"
- Update version in `pyproject.toml` (e.g., 1.0.0 → 1.0.1)
- Rebuild: `python -m build`

---

## One-Line Summary

**Your app is now installable worldwide:**
```bash
pip install wispr_dragon
```

That's it! 🚀
