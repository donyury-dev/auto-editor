# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o Auto Editor.

Uso:
    python -m PyInstaller build.pyinstaller.spec --clean --noconfirm

O resultado fica em dist/AutoEditor/ (one-dir).
"""

from __future__ import annotations

from pathlib import Path

import PyInstaller.config

PyInstaller.config.CONF["workpath"] = str(Path("build").resolve())

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("config", "config"),
        ("models", "models"),
        ("bin/ffmpeg", "bin/ffmpeg"),
    ],
    hiddenimports=[
        "faster_whisper",
        "faster_whisper.transcribe",
        "ctranslate2",
        "PyQt6",
        "PyQt6.sip",
        "anthropic",
        "openai",
        "keyring",
        "PIL",
        "dotenv",
        "requests",
        "cv2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # aplicação GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AutoEditor",
)
