# Wispr-Dragon Macro System Guide

The macro system lets you trigger programs, scripts, keystrokes, and text injection with voice commands — similar to Dragon 16.1 macros.

## Quick Start

### 1. Create a Macro File

Create `~/.wispr_dragon/macros/custom.yaml`:

```yaml
macros:
  - trigger: "open browser"
    action: launch
    program: firefox

  - trigger: "type email"
    action: text
    content: "jon@example.com"

  - trigger: "next tab"
    action: keystroke
    keys: ctrl+Tab
```

### 2. Use a Macro

Say "open browser" — Wispr Dragon will launch Firefox. Say "next tab" and it sends Ctrl+Tab.

---

## Macro Actions

### 1. Launch Programs

```yaml
- trigger: "open {app}"
  action: launch
  program: "{app}"
```

Say "open firefox" and it runs `firefox`. Programs must be in your PATH.

### 2. Inject Text

```yaml
- trigger: "type my password"
  action: text
  content: "correct horse battery staple"
```

Say "type my password" and the text is typed automatically.

### 3. Send Keystrokes

```yaml
- trigger: "undo last"
  action: keystroke
  keys: ctrl+z

- trigger: "save and quit"
  action: keystroke
  keys: ctrl+s,alt+F4
```

Valid keys: alphanumeric, plus operators like `+`, `-`, `_`, and xdotool key names.

### 4. Run Python Scripts

```yaml
- trigger: "run my script"
  action: python_script
  script: my_script.py
```

Scripts must be signed first. See below.

---

## Python Scripts

### Sign a Script

```bash
wispr_dragon --sign-script my_script.py
```

This adds the script to `~/.wispr_dragon/scripts/.manifest.json` with its SHA-256 hash.

### Script Format

Place scripts in `~/.wispr_dragon/scripts/`:

```python
# my_script.py
print("Hello from voice!")
```

When triggered, the script runs in a subprocess. Its stdout is optionally injected as text.

### Modifying Scripts

If you edit a signed script, you must re-sign it:

```bash
wispr_dragon --sign-script my_script.py
```

An unsigned or modified script will be rejected.

---

## Security

### Admin Lock (Password-Protected)

Restrict macros for shared accounts (e.g., family computer):

```bash
wispr_dragon --admin-lock
# Enter a password, confirm it
```

With the lock active, someone would need the password to:
- Run Python scripts
- Launch programs
- Use YAML macros

To unlock:

```bash
wispr_dragon --admin-unlock
# Enter password
```

### Dictation-Only Mode

Disable all macros for focused writing:

```bash
wispr_dragon --dictation-only
```

Or set in config:

```yaml
security:
  dictation_only: true
```

### Config-Based Restrictions

In `~/.wispr_dragon/config.yaml`:

```yaml
security:
  allow_python_scripts: false    # Disable Python scripts
  allow_yaml_macros: false       # Disable YAML macros
  allow_program_launch: false    # Disable program launching
  dictation_only: false          # Allow all modes
```

Useful for restricting certain features while keeping others.

---

## Placeholders

Macros support text placeholders. Say "open firefox" and it matches the trigger "open {app}" with `app=firefox`:

```yaml
- trigger: "open {app}"
  action: launch
  program: "{app}"
```

Placeholders extract one word or phrase (alphanumeric + spaces).

---

## Security Policy (3 Layers)

1. **Config flags** — Basic allow/deny settings in config.yaml
2. **Admin lock** — Password-protected override (blocks all if locked)
3. **Script signing** — SHA-256 manifest prevents unsigned/modified scripts

Admin lock overrides config flags. Script signing always required if Python is enabled.

---

## Troubleshooting

### "Script signature check failed"

The script's file hash doesn't match the manifest. You edited it. Re-sign:

```bash
wispr_dragon --sign-script my_script.py
```

### "Program not found in PATH"

The program isn't in your system PATH. Use the full path:

```yaml
- trigger: "open gimp"
  action: launch
  program: "/usr/bin/gimp"
```

Or install the program properly.

### "Invalid keystroke pattern"

Only alphanumeric + `+`, `-`, `_` are allowed. Fix:

```yaml
keys: "ctrl+alt+t"  # ✓ OK
keys: "super"       # ✓ OK
keys: "ctrl+alt+Delete"  # ✗ Capital D not allowed, use lowercase
```

Use lowercase for key names.

---

## Status Check

View current security policy:

```bash
wispr_dragon --security-status
```

Output:

```
=== Wispr-Dragon Security Status ===

Status: UNLOCKED

Policy Settings:
  Allow Python scripts:    true
  Allow YAML macros:       true
  Allow program launch:    true
  Dictation-only mode:     false
```

---

## Examples

### Productivity

```yaml
macros:
  - trigger: "open slack"
    action: launch
    program: slack

  - trigger: "open jira"
    action: launch
    program: firefox
    args: ["https://jira.company.com"]

  - trigger: "save my work"
    action: keystroke
    keys: ctrl+s
```

### Writing

```yaml
macros:
  - trigger: "focus mode"
    action: keystroke
    keys: F11  # Full screen

  - trigger: "paste link"
    action: text
    content: "https://example.com"
```

### Automation

```yaml
macros:
  - trigger: "backup files"
    action: python_script
    script: backup.py

  - trigger: "check email"
    action: python_script
    script: check_email.py
```

Sign the scripts first:

```bash
wispr_dragon --sign-script backup.py
wispr_dragon --sign-script check_email.py
```

---

## File Locations

- **Macros:** `~/.wispr_dragon/macros/*.yaml`
- **Scripts:** `~/.wispr_dragon/scripts/`
- **Script manifest:** `~/.wispr_dragon/scripts/.manifest.json`
- **Admin lock:** `~/.wispr_dragon/security.lock`
- **Config:** `~/.wispr_dragon/config.yaml`

---

## Next: Confirmation Dialog

When you say a command while writing (dictation mode), Wispr Dragon will show a confirmation dialog:

```
┌──────────────────────────────────────────┐
│ Wispr Dragon — Command Detected          │
│                                          │
│ While writing, a command was recognized: │
│ "open browser" → launch: firefox         │
│                                          │
│ [ Yes, run it ] [ No, type it ] [ Trust always ] │
└──────────────────────────────────────────┘
```

This prevents accidental macro execution while dictating.
