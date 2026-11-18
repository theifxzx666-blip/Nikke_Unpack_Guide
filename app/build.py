# -*- coding: utf-8 -*-
"""打包取件库客户端（onedir，避免 onefile 解压到 C 盘 tmpdir）"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 用带版本号的输出目录：PyInstaller 打包前会删除同名旧目录，
# 而本机的安全删除保护会拦截批量删除，导致打包直接失败。
TAG = sys.argv[1] if len(sys.argv) > 1 else "v2"
DIST = os.path.join(HERE, "dist_" + TAG)
WORK = os.path.join(HERE, "build_pyi_" + TAG)

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--name", "NikkePickup",
    # 必须用 --console：--windowed 下 sys.stdout 为 None，pywebview 会静默失败，
    # 表现为进程活着却没有窗口。控制台窗口由 main.py 的 prepare_env() 隐藏。
    "--windowed" if "--windowed" in sys.argv else "--console",
    "--add-data", os.path.join("ui", "index.html") + ";ui",
    "--hidden-import", "webview.platforms.edgechromium",
    "--hidden-import", "webview.platforms.winforms",
    "--hidden-import", "clr",
    # pythonnet 的 Python.Runtime.dll 不在默认收集范围内，缺了会导致窗口起不来且无报错
    "--collect-all", "pythonnet",
    "--collect-all", "clr_loader",
    "--collect-all", "webview",
    "--exclude-module", "UnityPy",
    "--exclude-module", "numpy",
    "--distpath", DIST,
    "--workpath", WORK,
    "main.py",
]

print("执行:", " ".join(cmd))
r = subprocess.run(cmd, cwd=HERE)
if r.returncode != 0:
    print("打包失败，退出码", r.returncode)
    sys.exit(r.returncode)

exe = os.path.join(DIST, "NikkePickup", "NikkePickup.exe")
print("完成:", exe, os.path.getsize(exe) if os.path.exists(exe) else "缺失")
