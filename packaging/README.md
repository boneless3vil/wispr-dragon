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
| `wispr_dragon_client.spec` | PyInstaller onedir spec. Bundles sounddevice's PortAudio DLL, names the Win32 pynput backends, and excludes the server/ML stack and unused Qt modules. |
| `wispr_dragon_client.iss` | Inno Setup script that wraps the onedir output into a per-user double-click installer (Start-Menu shortcut + uninstaller, optional desktop icon). |

## Prerequisites (Windows)

A Python 3.11 environment with the client dependencies **plus PyInstaller**.
The dev machine uses `C:\Users\<you>\.venvs\wispr_dragon\`:

```powershell
$py = "$HOME\.venvs\wispr_dragon\Scripts\python.exe"
& $py -m pip install pyinstaller          # client deps already present
```

Client deps, if starting fresh: `pip install -e ".[client]"` (from the repo),
which pulls websockets, pynput, PyQt6, qasync, sounddevice, numpy.

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
(`%LOCALAPPDATA%\WisprDragon\config.json`): `server_url`, `api_key`.

## Installer (Inno Setup)

Wraps the onedir bundle into a single per-user installer. Requires Inno Setup 6
(`winget install --id JRSoftware.InnoSetup --scope user`). ISCC lands at
`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`.

```powershell
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
$iss  = "\\wsl.localhost\Ubuntu\home\jon\wispr_dragon\packaging\wispr_dragon_client.iss"
& $iscc /O"$HOME\wd_build" /DSourceDir="$HOME\wd_build\dist\WisprDragonClient" $iss
```

Output: `$HOME\wd_build\WisprDragonClient-Setup-<version>.exe` (~35 MB,
lzma2-compressed). Installs to the user's Programs folder with no UAC prompt,
adds a Start-Menu shortcut + uninstaller, and offers an optional desktop icon.
`/DSourceDir` overrides the bundle location; `/O` sets the output dir.

## Notes & follow-ons

- **onedir vs onefile**: this spec is onedir (faster startup, fewer AV false
  positives, reliable DLL loading). For a single-file `.exe`, set `onefile` by
  collapsing `EXE`/`COLLECT` into one `EXE(..., a.binaries, a.datas, ...)`; it
  unpacks to a temp dir each launch and is more AV-prone.
- **console window**: the spec uses `console=True` so transcripts/logs are
  visible. For a pure tray app, set `console=False` in the spec's `EXE(...)`.
- **Icon**: add `icon='path\\to\\app.ico'` to `EXE(...)` once a real icon exists
  (the tray currently uses Qt's built-in play/pause pixmaps as placeholders).
- **Console encoding**: `--list-devices` may show `?`/garbled `®`/`—` in older
  consoles — a cp1252 code-page artifact in print output, not a build problem.
