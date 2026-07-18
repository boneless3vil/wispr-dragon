# Config directory migration

## Problem

`config.py:13-19` has compatibility logic between the old `~/.wispr-dragon` and the new `~/.wispr_dragon`:

```python
if not DEFAULT_USER_DIR.exists() and OLD_USER_DIR.exists():
    DEFAULT_USER_DIR = OLD_USER_DIR
```

This is a band-aid. Users with both dirs (because they ran a newer version that created the new one) silently lose access to their old config. And the fallback adds permanent complexity to every code path that touches user data.

## Fix

Migration tool — one-time, idempotent:

```python
def migrate_user_dir():
    new = Path.home() / ".wispr_dragon"
    old = Path.home() / ".wispr-dragon"
    if not old.exists() or new.exists():
        return
    logger.info("Migrating ~/.wispr-dragon → ~/.wispr_dragon")
    shutil.copytree(old, new)
    # Leave the old dir but rename a marker so we don't migrate again:
    (old / "MIGRATED_TO_NEW_PATH").write_text(str(new))
```

Run on first startup of a version >= the cutoff. After 2-3 releases, drop the fallback at `config.py:18` and the migration code.

## Affected

- `wispr_dragon/config.py`.
- New `wispr_dragon/migrations.py`.
- `wispr_dragon/__main__.py` — call migrate on startup.

## Effort

Trivial.
