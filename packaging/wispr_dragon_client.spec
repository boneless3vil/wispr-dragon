# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Wispr Dragon Windows client (onedir build).

Build (from a Windows shell, with the client venv's python):
    python -m PyInstaller --noconfirm packaging/wispr_dragon_client.spec

Produces dist/WisprDragonClient/WisprDragonClient.exe — a standalone client
that talks to the WSL transcription server. The heavy server stack
(faster-whisper / torch / CUDA) is NOT part of this bundle; the client only
captures audio, streams it over a WebSocket, and injects the returned text.
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# SPECPATH is the directory containing this spec (…/packaging); the repo root
# is its parent, and must be on pathex so `wispr_dragon` imports during analysis.
REPO_ROOT = os.path.dirname(SPECPATH)
ENTRY = os.path.join(SPECPATH, "client_entry.py")

# sounddevice ships the PortAudio DLL as a data/binary payload; pull both so the
# frozen client can open the mic without a system PortAudio install.
datas = collect_data_files("sounddevice")
binaries = collect_dynamic_libs("sounddevice")

a = Analysis(
    [ENTRY],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "sounddevice",
        # pynput resolves its backend lazily by platform; name the Win32 ones.
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Server-only / heavy deps — never reached by the client, excluded so a
        # stray transitive import can't bloat the bundle with CUDA or models.
        "torch", "faster_whisper", "ctranslate2", "whisper", "openai",
        "wispr_dragon.engine", "wispr_dragon.server",
        # Unused GUI/plotting weight.
        "matplotlib", "tkinter",
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebChannel",
        "PyQt6.Qt3DCore", "PyQt6.QtMultimedia", "PyQt6.QtQuick", "PyQt6.QtQml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WisprDragonClient",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True keeps the transcript/log stream visible. Flip to False once
    # the tray UX is the only intended surface.
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WisprDragonClient",
)
