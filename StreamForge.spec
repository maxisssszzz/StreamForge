# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import shutil
from PyInstaller.utils.hooks import collect_all

PROJECT_DIR = Path(SPECPATH).resolve()
FFMPEG_EXECUTABLE = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
if not FFMPEG_EXECUTABLE:
    raise SystemExit('FFmpeg not found. Install the Gyan FFmpeg full shared build before packaging.')
FFMPEG_DIR = Path(FFMPEG_EXECUTABLE).resolve().parent
FFMPEG_ROOT = FFMPEG_DIR.parent
FFMPEG_FILES = [FFMPEG_DIR / name for name in ('ffmpeg.exe', 'ffprobe.exe')]
FFMPEG_FILES += sorted(FFMPEG_DIR.glob('*.dll'))
if any(not path.is_file() for path in FFMPEG_FILES[:2]) or not list(FFMPEG_DIR.glob('*.dll')):
    raise SystemExit('The selected FFmpeg installation is incomplete; ffmpeg.exe, ffprobe.exe, and DLLs are required.')

datas = [
    (str(PROJECT_DIR / 'streamforge_minimalist_media_downloader.html'), '.'),
    (str(FFMPEG_ROOT / 'LICENSE'), 'ffmpeg'),
    (str(FFMPEG_ROOT / 'README.txt'), 'ffmpeg'),
    (str(PROJECT_DIR / 'THIRD_PARTY_NOTICES.md'), '.'),
]
binaries = [(str(path), 'ffmpeg') for path in FFMPEG_FILES]
hiddenimports = []
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(PROJECT_DIR / 'streamforge_launcher.py')],
    pathex=[str(PROJECT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StreamForge-v0.2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
