# Push to GitHub - Copy & Paste Commands

## Before You Start

1. Make sure you have a GitHub account (https://github.com/signup if not)
2. Create a new repository at https://github.com/new with:
   - Name: `wispr-dragon`
   - Public (recommended)
   - NO README (you have one already)

## Step 1: Set Up Remote (Do This Once)

Copy and paste these commands (replace `YOUR_USERNAME` with your GitHub username):

```bash
git remote add origin https://github.com/YOUR_USERNAME/wispr-dragon.git
```

Example:
```bash
git remote add origin https://github.com/JonathanBaldwin/wispr-dragon.git
```

## Step 2: Push Main Branch

```bash
git push -u origin main
```

This uploads the `main` branch (original stable code).

## Step 3: Push Feature Branch

```bash
git push -u origin feature/gpt-5.5-support
```

This uploads your experimental branch with GPT 5.5 support.

## Verify It Worked

Go to: `https://github.com/YOUR_USERNAME/wispr-dragon`

You should see:
- ✅ Both branches listed
- ✅ All files visible
- ✅ README.md displayed
- ✅ Commit history shown

## If You Get Errors

### "fatal: not a git repository"
You're in the wrong directory. Make sure you're in wispr-dragon:
```bash
cd wispr-dragon
pwd
```

### "fatal: remote origin already exists"
Someone already added the remote. Try:
```bash
git remote -v  # See what's there
git remote remove origin
# Then run Step 1 again
```

### "Permission denied"
GitHub needs to authenticate. It will prompt for login.

### "fatal: 'origin' does not appear to be a 'git' repository"
Double-check your username in the URL (Step 1).

## After First Push

Later pushes are easier:

```bash
# Just push current branch
git push

# Or push specific branch
git push origin feature/gpt-5.5-support
```

## Summary

Three commands, done:

```bash
git remote add origin https://github.com/YOUR_USERNAME/wispr-dragon.git
git push -u origin main
git push -u origin feature/gpt-5.5-support
```

Then verify at: `https://github.com/YOUR_USERNAME/wispr-dragon`

That's it! You're live on GitHub. 🎉
