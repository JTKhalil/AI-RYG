# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['cursor_light_app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/tray_icon.png', 'assets')],
    hiddenimports=['serial', 'serial.tools.list_ports', 'pystray', 'PIL', 'PIL._tkinter_finder', 'tkinter', 'single_instance'],
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
    name='CodingLight',
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
    icon='assets/tray_icon.ico',
)
