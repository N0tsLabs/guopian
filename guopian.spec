# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 过片 Guopian.

    pyinstaller guopian.spec --noconfirm --clean

Produces a portable folder containing:
    guopian.exe       windowed one-click app
    guopian-cli.exe   same program with a console (--report / scripting)

Things that cost real time to figure out, written down so nobody repeats them:

  * mediapipe imports matplotlib unconditionally, so matplotlib cannot be
    excluded even though Guopian never plots anything.
  * mediapipe ships .tflite/.binarypb blobs under mediapipe/modules/ -- data
    files, not code, invisible to import analysis. collect_all finds them.
  * MEDIAPIPE NEEDS unittest AT RUNTIME. Excluding unittest (a tempting
    size win) breaks face detection with "No module named 'unittest'".
  * PyInstaller's own hook-cv2.py *explicitly* adds opencv_videoio_ffmpeg*.dll,
    so filtering the binaries we collect is not enough -- the removal has to
    happen after Analysis.
  * the venv is built with --system-site-packages, so the interpreter can see
    unrelated heavy packages (torch, scipy, pandas). They must be excluded
    explicitly or the bundle grows by hundreds of megabytes.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(SPECPATH)
ASSETS = os.path.join(ROOT, "guopian", "assets")

ICON = None
for cand in ("guopian.ico", "guopian.png", "guopian.icns"):
    p = os.path.join(ASSETS, cand)
    if os.path.exists(p):
        ICON = p
        break

# --------------------------------------------------------------- what to drop
# ~47 MB of FFmpeg video backends (two copies) -- we never open a video.
# ~22 MB of libx265, the HEVC *encoder*: we only ever decode, and it is GPL.
DROP_BINARIES = ("opencv_videoio_ffmpeg", "x265")

# ---------------------------------------------------------------- datas
datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "models"), "models"),
    (ASSETS, "guopian/assets"),
]
binaries = []

hiddenimports = [
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "PIL._tkinter_finder",
    "guopian.rthook",
    # mediapipe reaches for these dynamically, so analysis alone misses them
    "unittest",
    "unittest.mock",
    "unittest.case",
    "unittest.result",
    "unittest.runner",
]

_UNUSED_MP = ("mediapipe.tasks.python.audio", "mediapipe.tasks.python.text")

mp_datas, mp_bins, mp_hidden = collect_all("mediapipe")
# Drop unused task families and the bundled *_test.py modules (they drag in
# test-only dependencies and bloat the archive).
mp_hidden = [h for h in mp_hidden
             if not h.startswith(_UNUSED_MP) and not h.endswith("_test")]
datas += mp_datas
binaries += mp_bins
hiddenimports += mp_hidden

# OpenCV
binaries += collect_dynamic_libs("cv2")
datas += collect_data_files("cv2")
hiddenimports += ["cv2"]

# HEIC
try:
    heif_datas, heif_bins, heif_hidden = collect_all("pillow_heif")
    datas += heif_datas
    binaries += heif_bins
    hiddenimports += heif_hidden
except Exception:
    pass

# ---------------------------------------------------------------- excludes
excludes = [
    # present in the interpreter's site-packages, never imported by Guopian
    "torch", "torchvision", "torchaudio", "tensorflow", "tensorboard",
    "jax", "jaxlib", "flax", "scipy", "pandas", "pandas.compat",
    "sklearn", "numba", "llvmlite", "cupy", "paddle", "paddlepaddle",
    "onnx", "onnxruntime", "dlib", "IPython", "jupyter", "notebook",
    "nbformat", "nbconvert", "sphinx", "pytest",
    # GUI toolkits we do not use (tkinter IS used, so it stays)
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi",
    "matplotlib.backends.backend_qt5agg", "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_webagg", "matplotlib.backends._backend_tk",
    "matplotlib.backends.backend_gtk3", "matplotlib.backends.backend_wx",
    "matplotlib.tests", "numpy.tests", "PIL.ImageQt",
    # mediapipe paths we never touch
    "sounddevice", "mediapipe.tasks.python.audio", "mediapipe.tasks.python.text",
]

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, "guopian", "rthook.py")],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Removal has to happen here: PyInstaller's own hooks add the FFmpeg DLLs
# during Analysis, after our own collection already ran.
_before_b = len(a.binaries)
a.binaries = [b for b in a.binaries
              if not any(t in os.path.basename(b[0]).lower() for t in DROP_BINARIES)]
a.datas = [d for d in a.datas
           if not any(t in os.path.basename(d[0]).lower() for t in DROP_BINARIES)]
print("guopian.spec: dropped {} binaries ({})".format(
    _before_b - len(a.binaries), ", ".join(DROP_BINARIES)))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="guopian",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # no console window: a real one-click app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

exe_cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="guopian-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,               # keeps --report usable from a terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Guopian",
)

# ------------------------------------------------------------------ macOS
# On macOS a bare executable folder is not a usable app: Finder, Gatekeeper
# and notarisation all want a real .app bundle with an Info.plist.
if sys.platform == "darwin":
    app = BUNDLE(
        exe_gui,
        name="Guopian.app",
        icon=ICON,
        bundle_identifier="top.n0ts.guopian",
        version="0.1.0",
        info_plist={
            "CFBundleName": "过片 Guopian",
            "CFBundleDisplayName": "过片 Guopian",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.photography",
            "NSCameraUsageDescription": "过片不需要相机。",
            "NSHumanReadableCopyright": "MIT License",
        },
    )
