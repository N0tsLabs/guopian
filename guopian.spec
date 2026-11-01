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
#
# libx265 used to be dropped here too, on the theory that "we only decode".
# That is true of the app but not of libheif: it links libx265 at load time, so
# removing it made `import _pillow_heif` fail and HEIC support vanish from the
# packaged build with no error anywhere (found by inspecting /api/home's
# capabilities: heic.ok was false). 21 MB is the price of the feature.
DROP_BINARIES = ("opencv_videoio_ffmpeg",)

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
#
# pillow_heif 的 libheif 不在包目录里：轮子把它 .dll 直接放在 site-packages 根，
# 旁边才是 `_pillow_heif.*.pyd`。collect_all 只扫包目录，于是打包版能 import
# pillow_heif，却在加载 _pillow_heif 时因为找不到 libheif 而失败 —— 而 imageio
# 把那个 ImportError 吞成了 HAVE_HEIF=False，表现就是"HEIC 照片进不了库"，
# 没有任何报错。实测自检里 heic: False 才发现。
try:
    heif_datas, heif_bins, heif_hidden = collect_all("pillow_heif")
    datas += heif_datas
    binaries += heif_bins
    hiddenimports += heif_hidden
    import glob
    import pillow_heif

    _sp = os.path.dirname(os.path.dirname(os.path.abspath(pillow_heif.__file__)))
    # 不是一个 DLL：delvewheel 把 libheif 连同它的依赖（libde265 / x265 /
    # libstdc++ / libwinpthread / libgcc）一起放在 site-packages 根目录，
    # 一个都不能少 —— 少一个就是 "DLL load failed while importing _pillow_heif"。
    _heif_dlls = []
    for _pat in ("libheif-*.dll", "libde265-*.dll", "libx265-*.dll",
                 "libstdc++-*.dll", "libgcc_s_seh-*.dll", "libwinpthread-*.dll"):
        _heif_dlls += glob.glob(os.path.join(_sp, _pat))
    for _dll in _heif_dlls:
        binaries.append((_dll, "."))
    print("guopian.spec: +pillow_heif dlls:",
          ", ".join(os.path.basename(d) for d in _heif_dlls))
except Exception as _e:                                   # pragma: no cover
    print("guopian.spec: pillow_heif collect failed:", _e)

# ---------------------------------------------------------------- excludes
excludes = [
    # present in the interpreter's site-packages, never imported by Guopian
    "torch", "torchvision", "torchaudio", "tensorflow", "tensorboard",
    "jax", "jaxlib", "flax", "scipy", "pandas", "pandas.compat",
    "sklearn", "numba", "llvmlite", "cupy", "paddle", "paddlepaddle",
    # onnxruntime 曾经也在这里 —— 那时照片向量还是可选项。现在相似分组默认
    # 用它，排掉它等于让打包版静默退回 pHash（模型在、但它加载不了）。
    "onnx", "dlib", "IPython", "jupyter", "notebook",
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

# onnxruntime 是原生扩展：它的 .pyd/.dll 不会被 import 分析带进来，
# 必须显式收集，否则打包版 exec 到 embed.session() 时才炸。
try:
    _ort_datas, _ort_bins, _ort_hidden = collect_all("onnxruntime")
    datas += _ort_datas
    binaries += _ort_bins
    hiddenimports += _ort_hidden
except Exception as _e:                                   # pragma: no cover
    print("guopian.spec: onnxruntime collect failed:", _e)

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
