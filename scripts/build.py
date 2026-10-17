#!/usr/bin/env python3
"""Build a distributable Guopian for the current platform.

    python scripts/build.py            # build + package
    python scripts/build.py --clean    # wipe build/, dist/, release/

Output lands in release/:
    Windows   Guopian-<ver>-windows-x64.zip
    macOS     Guopian-<ver>-macos-<arch>.zip      (contains Guopian.app)
    Linux     Guopian-<ver>-linux-x64.tar.gz      (contains Guopian/ + .desktop)

There is no cross-compilation: a macOS build has to run on macOS and a Linux
build on Linux. That is what .github/workflows/build.yml is for.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
RELEASE = os.path.join(ROOT, "release")
VERSION = "0.1.0"

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=过片 Guopian
Name[en]=Guopian
Comment=本地照片筛选 / local photo culling
Exec=guopian %f
Icon=guopian
Terminal=false
Categories=Graphics;Photography;
MimeType=image/jpeg;image/png;image/webp;image/heic;image/tiff;
"""

# Shipped inside the extracted folder. A portable app whose folder contains
# three entries and two of them are not the one you want needs a signpost.
README_TXT = """过片 Guopian {ver} — 本地照片筛选工具
==================================================

双击运行哪个？
    guopian.exe          <-- 就是这个。双击它。

其余的东西不用管：
    guopian-cli.exe      同一个程序，但带一个控制台窗口。
                         平时不需要；出问题时用它排查（见下）。
    _internal\\           程序运行需要的文件（Python 运行时、人脸模型、
                         界面文件）。不要删除、不要改名、不要移动。

第一次运行
    会弹出文件夹选择器，选一个放照片的文件夹，然后浏览器会自动打开。
    之后它会记住你上次选的目录，双击就直接进去。

怎么用
    <-  移除（只是标记，不会删文件）
    ->  保留
    ^   待定（拿不准的丢这里）
    v   跳过
    Ctrl+Z  撤销（无限次）
    按住 Z  放大到 100% 看是否对焦，松开还原
    I   显示/隐藏人脸框、眼睛框
    P   过曝斑马纹
    T   按问题类型筛选（"把闭眼的给我看一遍"）
    G   网格视图
    ?   查看全部快捷键

照片安全
    * 筛选过程中一个字节都不会动你的原图，只写数据库。
    * 点"应用决策"后还要再确认一次，而且只是移动到隔离文件夹，
      不是删除，随时可以一键回滚。
    * 全程本地处理，不联网，不上传任何照片。
    * 索引和缩略图存在用户数据目录，不会往你的照片文件夹里塞东西：
          Windows  %LOCALAPPDATA%\\guopian

想放到 U 盘上带着走？
    在程序目录里新建一个空文件，名字叫：  guopian.portable
    索引就会存在程序目录下的 catalogs\\ 里。

出问题了怎么办
    1. 先用带控制台的版本跑一次，就能看到实时输出：
           guopian-cli.exe "D:\\你的照片文件夹"
    2. 让程序自己把整条链路体检一遍：
           guopian-cli.exe "D:\\你的照片文件夹" --selftest
    3. 日志在这个文件里：
           %LOCALAPPDATA%\\guopian\\guopian.log
       把它发到 GitHub Issue 就行。

macOS 用户注意
    首次打开若提示"无法验证开发者"，是因为没有购买 Apple 签名。
    右键点 Guopian.app -> 选"打开" -> 再点"打开"，只需一次。

许可证  MIT       项目主页  https://github.com/N0ts/guopian
"""


def write_readme_txt(src_dir: str) -> None:
    path = os.path.join(src_dir, "使用说明.txt")
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(README_TXT.format(ver=VERSION))
    except Exception as e:
        print("  (could not write 使用说明.txt: {})".format(e))


def run(cmd: list[str]) -> int:
    print("  $", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def py() -> str:
    """The interpreter to use: prefer the project venv."""
    for cand in (os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
                 os.path.join(ROOT, ".venv", "bin", "python")):
        if os.path.exists(cand):
            return cand
    return sys.executable


def ensure_models() -> None:
    model = os.path.join(ROOT, "models", "face_landmarker.task")
    if os.path.exists(model) and os.path.getsize(model) > 0:
        print("  models: ok")
        return
    print("  models: fetching...")
    run([py(), os.path.join(ROOT, "scripts", "fetch_models.py")])


def ensure_icon() -> None:
    if os.path.exists(os.path.join(ROOT, "guopian", "assets", "guopian.ico")):
        print("  icon: ok")
        return
    print("  icon: generating...")
    run([py(), os.path.join(ROOT, "scripts", "make_icon.py")])


def platform_tag() -> tuple[str, str]:
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(sysname, sysname)
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return os_name, arch


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_size(path: str) -> float:
    total = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total / (1024 * 1024)


# ------------------------------------------------------------------ packaging

def make_zip(src_dir: str, out: str, arc_root: str) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, _, fs in os.walk(src_dir):
            for f in fs:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, src_dir)
                z.write(full, os.path.join(arc_root, rel))


def make_targz(src_dir: str, out: str, arc_root: str) -> None:
    with tarfile.open(out, "w:gz", compresslevel=6) as t:
        t.add(src_dir, arcname=arc_root)


def package() -> int:
    os_name, arch = platform_tag()
    os.makedirs(RELEASE, exist_ok=True)

    if os_name == "macos":
        src = os.path.join(DIST, "Guopian.app")
        name = "Guopian-{}-macos-{}.zip".format(VERSION, arch)
        out = os.path.join(RELEASE, name)
        if not os.path.isdir(src):
            print("  !! {} not found".format(src))
            return 1
        make_zip(src, out, "Guopian.app")
    elif os_name == "windows":
        src = os.path.join(DIST, "Guopian")
        name = "Guopian-{}-windows-{}.zip".format(VERSION, arch)
        out = os.path.join(RELEASE, name)
        if not os.path.isdir(src):
            print("  !! {} not found".format(src))
            return 1
        write_readme_txt(src)
        make_zip(src, out, "Guopian")
    else:
        src = os.path.join(DIST, "Guopian")
        name = "Guopian-{}-linux-{}.tar.gz".format(VERSION, arch)
        out = os.path.join(RELEASE, name)
        if not os.path.isdir(src):
            print("  !! {} not found".format(src))
            return 1
        write_readme_txt(src)
        # a .desktop entry and icon so it shows up in the application menu
        share = os.path.join(src, "share")
        os.makedirs(share, exist_ok=True)
        with open(os.path.join(share, "guopian.desktop"), "w", encoding="utf-8") as f:
            f.write(DESKTOP_ENTRY)
        png = os.path.join(ROOT, "guopian", "assets", "guopian.png")
        if os.path.exists(png):
            shutil.copy2(png, os.path.join(share, "guopian.png"))
        make_targz(src, out, "Guopian")

    digest = sha256(out)
    with open(out + ".sha256", "w", encoding="utf-8") as f:
        f.write("{}  {}\n".format(digest, os.path.basename(out)))

    print("\n  release/{}  ({:.1f} MB)".format(name, os.path.getsize(out) / (1024 * 1024)))
    print("  sha256 {}".format(digest))
    print("  unpacked {:.1f} MB".format(dir_size(src)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe build/ dist/ release/ first")
    ap.add_argument("--skip-build", action="store_true",
                    help="only re-package whatever is already in dist/")
    ap.add_argument("--skip-package", action="store_true")
    args = ap.parse_args()

    if args.clean:
        for d in (BUILD, DIST, RELEASE):
            shutil.rmtree(d, ignore_errors=True)
        print("  cleaned build/ dist/ release/")

    os_name, arch = platform_tag()
    print("== 过片 Guopian build ==")
    print("  platform: {} {}".format(os_name, arch))
    print("  python  : {}".format(py()))

    if not args.skip_build:
        ensure_models()
        ensure_icon()

        spec = os.path.join(ROOT, "guopian.spec")
        pyinstaller = os.path.join(os.path.dirname(py()), "pyinstaller")
        if os_name == "windows":
            pyinstaller += ".exe"
        if not os.path.exists(pyinstaller):
            print("  pyinstaller not found, installing...")
            run([py(), "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"])
            pyinstaller = os.path.join(os.path.dirname(py()), "pyinstaller")

        rc = run([pyinstaller, spec, "--noconfirm", "--clean", "--log-level", "WARN"])
        if rc != 0:
            print("  !! pyinstaller failed ({})".format(rc))
            return rc

    if args.skip_package:
        print("\n  built: dist/")
        return 0
    return package()


if __name__ == "__main__":
    sys.exit(main())
