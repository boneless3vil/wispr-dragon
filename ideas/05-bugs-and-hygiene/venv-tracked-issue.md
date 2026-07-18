# Confirm venv is gitignored

## Problem

Globbing the repo turned up files under `venv/lib/python3.13/site-packages/pip/…`. Either `venv/` is in the working tree but gitignored (fine), or it's being tracked (very bad — adds tens of thousands of files to git history on every checkout). Worth a 30-second verification.

## Fix

```sh
git check-ignore -v venv/ && echo "OK"
git ls-files venv/ | head
```

If `git ls-files` returns anything, that venv was committed somewhere in history. Run:

```sh
git rm -rf --cached venv/
echo "venv/" >> .gitignore
git commit -m "chore: untrack venv"
```

And review the contributor docs (`README` / `CONTRIBUTING.md`) to make sure new contributors don't recreate the mistake.

## Effort

Trivial.
