# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None


def _hook_payload() -> list[tuple[str, str]]:
    base = "dist/CodingLightHook"
    items: list[tuple[str, str]] = []
    if not os.path.isdir(base):
        return items
    for root, _dirs, files in os.walk(base):
        for name in files:
            src = os.path.join(root, name)
            rel_dir = os.path.relpath(root, "dist")
            items.append((src, os.path.join("payload", rel_dir)))
    return items


a = Analysis(
    ["installer_app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("dist/CodingLight.exe", "payload"),
        ("dist/CodingLightUninstall.exe", "payload"),
        ("assets/tray_icon.ico", "payload"),
        *_hook_payload(),
    ],
    hiddenimports=["tkinter"],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CodingLightSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/tray_icon.ico",
    uac_admin=True,
)
