# Git Cheatsheet for Wispr Dragon

## Your Current Setup

```
wispr-dragon (Local Repository)
├── main branch (original stable code)
└── feature/gpt-5.5-support (your experimental work - CURRENT)
```

**Currently on:** `feature/gpt-5.5-support` branch

---

## Basic Commands

### Check Status
```bash
git status                    # What files changed?
git branch                    # Which branch am I on?
git log --oneline            # What commits exist?
```

### Switch Branches
```bash
git checkout main             # Go to main branch
git checkout feature/gpt-5.5-support  # Go to feature branch
```

### Make Changes
```bash
git add .                     # Stage all changes
git add filename.py           # Stage specific file
git commit -m "Message"       # Create commit
```

### View Differences
```bash
git diff                      # What changed in current branch?
git diff main                 # Differences from main
git diff main feature/gpt-5.5-support  # Compare branches
```

---

## For GitHub (After Creating Repo)

### Initial Push
```bash
git remote add origin https://github.com/YOUR_USERNAME/wispr-dragon.git
git push -u origin main
git push -u origin feature/gpt-5.5-support
```

### Regular Push
```bash
git push                      # Push current branch
git push origin main          # Push main specifically
git push origin feature/gpt-5.5-support  # Push feature
```

### Pull Latest
```bash
git pull                      # Get latest from current branch
git pull origin main          # Get latest main
```

---

## Useful Patterns

### Add, Commit, Push (All Together)
```bash
git add .
git commit -m "Your message"
git push
```

### See What's Different from Main
```bash
git diff main
```

### Create New Branch
```bash
git checkout -b feature/new-feature
# Work, then:
git push -u origin feature/new-feature
```

### Merge Another Branch
```bash
git checkout main             # Switch to main
git merge feature/gpt-5.5-support  # Merge feature into main
git push                      # Push merge
```

### Undo Last Commit (keep changes)
```bash
git reset HEAD~1
```

### Undo Last Commit (discard changes)
```bash
git reset --hard HEAD~1
```

---

## Branch Switching Examples

```bash
# You're on feature/gpt-5.5-support, want to work on main
git checkout main

# Later, go back to feature
git checkout feature/gpt-5.5-support

# Check current branch
git branch
# * feature/gpt-5.5-support
#   main
```

---

## Daily Workflow

### Morning: Start Work
```bash
git pull                      # Get latest
git branch                    # Verify correct branch
```

### Work
```bash
# Edit files...
git status                    # See changes
```

### Before Break: Save Work
```bash
git add .
git commit -m "Work on [feature]: describe progress"
git push
```

### Evening: Finalize
```bash
git add .
git commit -m "Complete [feature]: describe final state"
git push
```

---

## Emergency Commands

### "Oops, I changed the wrong file"
```bash
git checkout -- filename.py   # Discard changes
```

### "I committed too much"
```bash
git reset HEAD~1              # Undo commit, keep files
```

### "What did I just push?"
```bash
git log --oneline -5          # See recent commits
```

### "I forgot what branch I'm on"
```bash
git branch                    # * shows current
```

---

## Information Commands

### See All Branches
```bash
git branch                    # Local only
git branch -a                 # Local + remote (after push)
```

### See Commit History
```bash
git log --oneline             # Compact history
git log --oneline -10         # Last 10 commits
git log --graph --all         # Visual with branches
```

### See Who Changed What
```bash
git blame filename.py         # Who changed each line?
```

### See Specific Commit
```bash
git show 6ebf387              # Show details of commit
```

---

## After GitHub Push

### See Remote Status
```bash
git remote -v                 # Show remote addresses
git branch -a                 # Show all branches (local + remote)
```

### Keep In Sync
```bash
git fetch origin              # Download latest info
git pull origin main          # Download and merge main
```

---

## Common Mistakes & Fixes

| Problem | Solution |
|---------|----------|
| On wrong branch | `git checkout correct-branch` |
| Forgot to push | `git push origin branch-name` |
| Pushed to wrong branch | No problem, git tracks everything separately |
| Accidentally deleted file | `git checkout -- filename` (if not committed) |
| Bad commit message | `git commit --amend` (before pushing) |
| Wrong API key | Delete key, don't commit, add to `.gitignore` |

---

## Pro Tips

✅ **Commit often** - Small commits are easier to understand
✅ **Write good messages** - Future you will thank current you
✅ **Pull before push** - Avoids conflicts
✅ **Branch for features** - Keep main clean and stable
✅ **Review before committing** - `git diff` shows changes
✅ **Use meaningful branch names** - `feature/`, `bugfix/`, `docs/`

---

## Your Branches Explained

### `main` Branch
- Contains: Original stable code
- When to use: Only merge stable, tested features
- Before push: Make sure tests pass
- Users download this by default

### `feature/gpt-5.5-support` Branch
- Contains: New GPT 5.5 API engine
- When to use: Development, testing, documentation
- Can break things - it's experimental
- Users download this for testing new features

---

## What Not To Do

❌ **Don't commit secrets** → Use `.env` files (in `.gitignore`)
❌ **Don't `git push --force`** → Unless you really know what you're doing
❌ **Don't commit large files** → Use `.gitignore`
❌ **Don't work on main directly** → Use feature branches
❌ **Don't forget to pull** → Before you start work

---

## Quick Reference: Your Setup

```bash
# See current state
git status

# See your branches
git branch

# See your commits
git log --oneline -5

# Switch to main (stable)
git checkout main

# Back to your work (experimental)
git checkout feature/gpt-5.5-support

# Push your work
git push
```

---

## After GitHub is Set Up

```bash
# See remotes
git remote -v

# Push everything
git push -u origin main
git push -u origin feature/gpt-5.5-support

# Later, just push
git push

# Or sync with GitHub
git pull
```

---

## Questions?

- `git help command` - Get help for any command
- `git status` - Always shows what you can do next
- See GITHUB_SETUP.md for detailed explanations
- See GITHUB_NEXT_STEPS.md for step-by-step guide
