# GitHub Setup Guide for Wispr_Dragon

Your local repository is now fully initialized! Here's how to connect it to GitHub and publish your code.

## What Was Just Set Up

✅ **Local Git Repository** - Initialized with 2 commits
✅ **.gitignore** - Prevents uploading secrets, large files, IDE configs
✅ **Main Branch** - Stable version (renamed from master)
✅ **Feature Branch** - `feature/gpt-5.5-support` for your new work

```
Your Local Computer
├── main branch (stable - original code)
└── feature/gpt-5.5-support (your new work)
```

## Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Fill in:
   - **Repository name:** `wispr-dragon`
   - **Description:** "Speech recognition with multi-engine support (faster-whisper, OpenAI Whisper, OpenAI API with GPT 5.5)"
   - **Visibility:** Public (so others can download)
   - **Do NOT** initialize with README (we already have one!)
3. Click "Create repository"

## Step 2: Connect Local Repo to GitHub

GitHub will show you the commands. Run these (replace `YOUR_USERNAME`):

```bash
git remote add origin https://github.com/YOUR_USERNAME/wispr-dragon.git
git branch -M main
git push -u origin main
```

If you already renamed to main locally, just run:
```bash
git remote add origin https://github.com/YOUR_USERNAME/wispr-dragon.git
git push -u origin main
```

## Step 3: Push Your Feature Branch

```bash
# Push the feature branch to GitHub
git push -u origin feature/gpt-5.5-support
```

After this, your GitHub will show:
- **main** branch - Original, stable code
- **feature/gpt-5.5-support** branch - Your new GPT 5.5 work

## Step 4: Verify on GitHub

Go to your GitHub repo: `https://github.com/YOUR_USERNAME/wispr-dragon`

You should see:
- ✅ Two branches (main, feature/gpt-5.5-support)
- ✅ All files uploaded
- ✅ README.md displayed on the homepage
- ✅ .gitignore protecting secrets

## Current Branch Structure

```
wispr-dragon (GitHub Repository)
│
├── main branch (default, what people download)
│   ├── Original faster-whisper engine
│   ├── OpenAI Whisper local engine
│   ├── Audio capture
│   └── Basic testing
│
└── feature/gpt-5.5-support (experimental)
    ├── + OpenAI API engine (NEW!)
    ├── + GPT 5.5 model support (ready when released)
    ├── + Improved testing (test_integration.py)
    ├── + Better audio initialization
    └── + Full documentation
```

## How People Will Download

**Get the stable version (original code):**
```bash
git clone https://github.com/YOUR_USERNAME/wispr-dragon.git
# Downloads main branch by default
```

**Try the GPT 5.5 version (for early testing):**
```bash
git clone -b feature/gpt-5.5-support https://github.com/YOUR_USERNAME/wispr-dragon.git
# Downloads the experimental branch
```

## Next Steps (After Testing)

Once you're confident the GPT 5.5 support is solid:

### Option A: Create a Pull Request (Recommended for Collaboration)

```bash
# Make sure you're on the feature branch
git checkout feature/gpt-5.5-support

# Push latest changes
git push origin feature/gpt-5.5-support
```

Then on GitHub.com:
1. Go to your repository
2. Click "Pull requests" tab
3. Click "New pull request"
4. Compare `feature/gpt-5.5-support` → `main`
5. Add description and click "Create pull request"

A PR is useful for:
- Getting feedback from others
- Discussing the changes
- Running automated tests
- Having a paper trail of what changed

### Option B: Merge Directly (Simple, No Collaboration)

If you're happy with the changes and working alone:

```bash
# Switch to main
git checkout main

# Pull latest
git pull origin main

# Merge feature branch into main
git merge feature/gpt-5.5-support

# Push to GitHub
git push origin main

# Delete feature branch (optional)
git branch -d feature/gpt-5.5-support
git push origin --delete feature/gpt-5.5-support
```

Now everyone downloading will get the new GPT 5.5 support!

## Keeping Branches Updated

If main gets updates while you're working on feature:

```bash
# Sync your feature branch with main
git fetch origin
git rebase origin/main

# Or merge if you prefer
git merge origin/main

# Push updated feature branch
git push origin feature/gpt-5.5-support -f
```

## Important Commands Reference

```bash
# Check which branch you're on
git branch

# Switch branches
git checkout main
git checkout feature/gpt-5.5-support

# See commit history
git log --oneline

# Show what changed
git diff main feature/gpt-5.5-support

# Add changes
git add .
git commit -m "Your message"

# Push to GitHub
git push origin branch-name

# Pull latest from GitHub
git pull origin branch-name
```

## Security Reminder

The `.gitignore` file protects:
- ❌ `OPENAI_API_KEY` - Never uploaded
- ❌ `.env` files - Never uploaded
- ❌ Large model files - Never uploaded
- ❌ IDE settings - Never uploaded
- ✅ Source code - Uploaded
- ✅ Documentation - Uploaded
- ✅ Tests - Uploaded

**Double-check before pushing:**
```bash
git status  # See what will be uploaded
```

## Troubleshooting

### "fatal: remote origin already exists"
```bash
git remote remove origin
# Then run the "Connect Local Repo" commands again
```

### "Permission denied (publickey)"
You need to set up SSH keys for GitHub:
1. https://docs.github.com/en/authentication/connecting-to-github-with-ssh
2. Or use HTTPS instead:
   ```bash
   git remote set-url origin https://github.com/YOUR_USERNAME/wispr-dragon.git
   ```

### "Updates were rejected because the remote contains work that you do not have locally"
```bash
git pull origin main  # Download latest
git push origin main  # Push again
```

## Summary

✅ **Local repo ready** - Git initialized with branches
✅ **Gitignore configured** - Secrets protected
✅ **Ready to push** - Just need GitHub account setup
✅ **Branch strategy** - main (stable) + feature (experimental)

**Next:** Create GitHub repo and push! (Steps 1-3 above)

---

## Questions?

- GitHub Basics: https://docs.github.com/en/get-started
- Branching Guide: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests
- Git Workflow: https://git-scm.com/book/en/v2
