# Packaging — Wispr Dragon Windows client

Builds the **client** (audio capture → WebSocket → text injection) into a
standalone Windows bundle so end users need no Python, conda, or PortAudio.

The **server** (faster-whisper / torch / CUDA) is deliberately *not* packaged —
it stays a developer install on the WSL2/Linux box. Only the lightweight client
ships. The client bundle contains no ML stack, so it stays ~120 MB.

## What's here

| File | Purpose |
|------|---------|
| `client_entry.py` | Frozen entry point. PyInstaller needs a real script, and the package's `__main__.py` uses a relative import that only works under `python -m`; this shim imports `wispr_dragon.client.app:main` absolutely. |
| `wispr_dragon_client.spec` | PyInstaller onedir spec. Bundles the tray icon artwork (`wispr_dragon/assets/*.png`), names the Win32 pynput backends and the lazily imported dialogs, and excludes the server/ML stack, the desktop UI (`wispr_dragon.ui`) and unused Qt modules. sounddevice's PortAudio DLL is picked up by pyinstaller-hooks-contrib's hook. |
| `wispr_dragon_client.iss` | Inno Setup script that wraps the onedir output into a per-user double-click installer (Start-Menu shortcut + uninstaller, optional desktop icon). |

## Prerequisites (Windows)

A Python 3.11 environment with the client dependencies **plus PyInstaller**.
The dev machine uses `C:\Users\<you>\.venvs\wispr_dragon\`:

```powershell
$py = "$HOME\.venvs\wispr_dragon\Scripts\python.exe"
& $py -m pip install pyinstaller          # client deps already present
```

Client deps, if starting fresh: `pip install -e ".[client]"` (from the repo),
which pulls websockets (12.x), pynput (>= 1.8, for the injected-key filter),
PyQt6, qasync and pystray/Pillow, plus the core sounddevice + numpy.
PyInstaller 6.x with a current `pyinstaller-hooks-contrib` is required (the
contrib hook is what bundles PortAudio).

## Build

PyInstaller must run on **Windows** (it produces a Windows exe). Source can live
on the WSL share; keep the build/dist output on a local Windows path so writes
aren't going over the `\\wsl.localhost` UNC mount.

```powershell
$py    = "$HOME\.venvs\wispr_dragon\Scripts\python.exe"
$spec  = "\\wsl.localhost\Ubuntu\home\jon\wispr_dragon\packaging\wispr_dragon_client.spec"
$build = "$HOME\wd_build"
& $py -m PyInstaller --noconfirm --workpath "$build\build" --distpath "$build\dist" $spec
```

Output: `$HOME\wd_build\dist\WisprDragonClient\WisprDragonClient.exe` (onedir —
ship the whole `WisprDragonClient\` folder).

## Smoke test

```powershell
$exe = "$HOME\wd_build\dist\WisprDragonClient\WisprDragonClient.exe"
& $exe --help
& $exe --list-devices      # exercises the bundled PortAudio
```

Live test (needs the WSL server running — `wispr_dragon --server`):

```powershell
& $exe                     # tray + PTT hotkey, types transcripts into focused app
& $exe --no-tray           # headless, prints transcripts
```

Point the client at the server via its config
(`%LOCALAPPDATA%\WisprDragon\config.json`): `server_url`, `api_key` (the
first-run setup dialog writes both). Optional keys:

| Key | Default | Meaning |
|-----|---------|---------|
| `hotkey` | `ctrl_r` | pynput key name (`f8`, `scroll_lock`, …) or a single character. |
| `mode` | `ptt` | `ptt` (hold to talk) or `toggle` (press to start / stop). |
| `inject_method` | `paste` | `paste` (clipboard + Ctrl+V) or `sendinput` (per-character keystrokes). |
| `paste_settle_ms` | `250` | How long after Ctrl+V the previous clipboard text is restored (0–2000). Raise it if Office / Electron apps paste your *old* clipboard. The wait doesn't block audio capture. |
| `allow_injected_hotkey` | `false` | Accept hotkey presses sent by software (VoiceAttack, AutoHotkey, Stream Deck, foot-pedal drivers). Off by default so the client's own synthesized Ctrl+V can't trip a Ctrl hotkey; the log notes the first ignored software press. |

Dictation pasted via the clipboard is marked to stay out of Win+V clipboard
history and cloud clipboard sync; your own clipboard text is put back afterwards
(unless you copied something new in the meantime).

The windowed build has no console; it logs to
`%LOCALAPPDATA%\WisprDragon\client.log` (rotating, 1 MB x 3). Dictated text is
only logged at DEBUG level, so it is not written there by default.

To check the tray artwork made it into the bundle:
`Test-Path "$HOME\wd_build\dist\WisprDragonClient\_internal\wispr_dragon\assets\mic_on.png"`.

## Installer (Inno Setup)

Wraps the onedir bundle into a single per-user installer. Requires Inno Setup 6
(`winget install --id JRSoftware.InnoSetup --scope user`). ISCC lands at
`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`.

```powershell
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
$iss  = "\\wsl.localhost\Ubuntu\home\jon\wispr_dragon\packaging\wispr_dragon_client.iss"
& $iscc /O"$HOME\wd_build" /DSourceDir="$HOME\wd_build\dist\WisprDragonClient" /DMyAppVersion=1.0.0 $iss
```

Output: `$HOME\wd_build\WisprDragonClient-Setup-<version>.exe` (~35 MB,
lzma2-compressed). Installs to the user's Programs folder with no UAC prompt,
adds a Start-Menu shortcut + uninstaller, and offers an optional desktop icon.
`/DSourceDir` overrides the bundle location; `/DMyAppVersion` sets the version
(default `1.0.0` — pass the pyproject version for real releases); `/O` sets the
output dir.

## Notes & follow-ons

- **onedir vs onefile**: this spec is onedir (faster startup, fewer AV false
  positives, reliable DLL loading). For a single-file `.exe`, set `onefile` by
  collapsing `EXE`/`COLLECT` into one `EXE(..., a.binaries, a.datas, ...)`; it
  unpacks to a temp dir each launch and is more AV-prone.
- **console window**: the spec uses `console=False` (pure tray app). Logs go to
  `client.log` (see above); problems such as a bad hotkey, a rejected API key
  or a missing microphone are shown as tray notifications. For a debugging
  build with a console, set `console=True` in the spec's `EXE(...)`.
- **Icon**: the tray uses the bundled `wispr_dragon/assets/mic_on.png` /
  `mic_off.png` (falling back to Qt's play/pause pixmaps only if they are
  missing). The `.exe` itself still has no icon — add `icon='path\\to\\app.ico'`
  to `EXE(...)` once an `.ico` exists.
- **Console encoding**: `--list-devices` may show `?`/garbled `®`/`—` in older
  consoles — a cp1252 code-page artifact in print output, not a build problem.
