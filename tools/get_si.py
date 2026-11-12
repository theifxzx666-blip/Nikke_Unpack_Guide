# -*- coding: utf-8 -*-
"""单件取 SI 立绘（国际服图集），落盘到资源库 `立绘SI/`。

为什么单独有它：`nk.py pull` 已经能取，但要手填 `--root`、手写完整 bundle 键、
导出后还要改名。这里把这些固定下来——只给代号就行：

    python tools/get_si.py c019_00
    python tools/get_si.py si_c019_00_s c472_00 -o D:/tmp/si

行为：
  1. 未给 --root 时从 Player.log 的 `trace GetGameResourcePath` 自动定位国际服客户端根；
  2. catalog 里查 `icons-char-si(hd)_assets_all_*` 键（hd 优先，128×128，与库内一致）；
  3. 取包 → UnityPy 按 Sprite 名裁剪导出 → 改名为 `si_<code>_s_intl.png` 落盘；
  4. 已存在同名文件时默认跳过（--force 覆盖）。

依赖：zstandard + UnityPy + Pillow（与 nk.py 相同）。国服没有 SI 小包，不在本脚本范围。
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # Nikke_Unpack_Guide
sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)                                       # nk.py 以 CWD 为工作根

import nk  # noqa: E402

SI_DIR = Path("F:/Codex/Nikke/01_母体/B_客户端资源/00_资源库/10_用户层/11_角色立绘/SI立绘")
# 国服（WeGame PC）：清单是明文 Addressables catalog，缓存按 <桶>/<hash> 存，NKAB 需 NAU
CN_CAT = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "com_tencent" / "胜利女神：新的希望" / "com.unity.addressables"
CN_CACHE = Path("E:/WeGameApps/rail_apps/胜利女神：新的希望(2002017)/nikke_Data/runtime_data/cache")
NAU = Path("F:/Codex/Nikke/01_母体/B_客户端资源/NAU/NAU.exe")


def cn_lookup(code):
    """国服 SI 单角色小包：清单里找 `si_<code>_s_<32hex>`，再在缓存里找同名 hash。"""
    import re as _re
    hits = []
    for f in CN_CAT.resolve().glob("*.json"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for c, h in _re.findall(r"icons-char-si\(sd\)_assets_si_(c\d+_\d+)_s_([0-9a-f]{32})\.bundle", t):
            if c == code:
                hits.append(h)
    if not hits:
        return None, "国服清单里没有 si_%s_s（未上线 / 键名变了）" % code
    if not CN_CACHE.is_dir():
        return None, "国服缓存目录不存在: %s" % CN_CACHE
    for h in set(hits):
        p = list(CN_CACHE.glob("*/" + h))
        if p:
            return p[0], ""
    return None, ("国服清单有键但缓存没下载（%d 个 hash 均未命中）——先在国服客户端里打开该角色/图鉴再试"
                  % len(set(hits)))


def cn_extract(path, out_png):
    """NKAB → NAU 解密 → UnityPy 取 Texture2D/Sprite。"""
    import shutil as _sh
    import tempfile
    import UnityPy
    tmp = Path(tempfile.mkdtemp(prefix="cnsi_"))
    try:
        head = path.read_bytes()[:4]
        bundle = path
        if head == b"NKAB":
            src = tmp / "in"
            dst = tmp / "out"
            src.mkdir()
            _sh.copy2(path, src / "b.bundle")
            dst.mkdir()
            if not NAU.is_file():
                return False, "缺 NAU: %s" % NAU
            import subprocess
            # NAU 结束时打印 "Press enter to continue"，空 stdin 下退出码可能是 1，
            # 所以只认产物，不看 rc。
            r = subprocess.run([str(NAU), "d", "-i", str(src), "-o", str(dst)],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=str(NAU.parent))
            got = [g for g in dst.rglob("*") if g.is_file() and g.stat().st_size > 8]
            if not got:
                return False, "NAU 没有产出 rc=%d %s" % (r.returncode, (r.stdout or "")[-200:])
            bundle = max(got, key=lambda g: g.stat().st_size)
        env = UnityPy.load(str(bundle))
        for o in env.objects:
            if o.type.name in ("Texture2D", "Sprite"):
                try:
                    img = o.read().image
                except Exception:
                    continue
                if img.size[0] >= 64:                      # 跳过 4×4 占位
                    img.save(str(out_png))
                    return True, "%dx%d" % img.size
        return False, "bundle 里没有可用贴图"
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


def guess_intl_root():
    """返回 (客户端根, 来源)。优先 Player.log 的 GetGameResourcePath，其次已知安装位置。"""
    log = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "com_proximabeta" / "NIKKE" / "Player.log"
    log = log.resolve()
    if log.is_file():
        try:
            txt = log.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            txt = ""
        hits = re.findall(r"GetGameResourcePath[^\n]*?([A-Za-z]:[\\/][^\s\"']+)", txt)
        for h in reversed(hits):
            p = Path(h.replace("\\", "/"))
            for cand in (p, p / "Unity" / "com_proximabeta_NIKKE"):
                if (cand / "com.shiftup.patch").is_dir():
                    return str(cand), "player.log"
    cands = [
        "D:/PanDownload/Nikke_local/NIKKEG/Unity/com_proximabeta_NIKKE",
        "D:/PanDownload/Nikke_local/NIKKEG",
        "E:/Nikke/NIKKEG/Unity/com_proximabeta_NIKKE",
        "F:/Nikke/NIKKEG/Unity/com_proximabeta_NIKKE",
        "C:/Nikke/NIKKEG/Unity/com_proximabeta_NIKKE",
    ]
    for cand in cands:
        if (Path(cand) / "com.shiftup.patch").is_dir():
            return cand, "fallback"
    return "", "none"


def si_bundle_key(root, bucket="dp"):
    """取 SI 图集键（hd 优先）。"""
    cat = nk._ensure_cat(root, bucket)
    import sqlite3
    con = sqlite3.connect(cat)
    keys = [r[0] for r in con.execute(
        "SELECT key FROM files_chunktype WHERE key LIKE 'icons-char-si%' ORDER BY key DESC")]
    con.close()
    hd = [k for k in keys if "(hd)" in k]
    if not hd:
        raise RuntimeError("catalog 里没有 icons-char-si(hd) 键，先跑 nk.py scan")
    return hd[0]


def norm_name(s):
    s = s.strip()
    if s.startswith("si_"):
        return s if s.endswith("_s") else s + "_s"
    m = re.match(r"c(\d+)_(\d+)", s)
    if not m:
        raise ValueError("看不懂的代号: %s（给 c019_00 或 si_c019_00_s）" % s)
    return "si_c%s_%s_s" % (m.group(1), m.group(2))


def run_cn(a):
    """国服分支：每角色一个小包，命中率取决于本地缓存有没有下载过该角色图标。"""
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = {"scene": "cn-pc", "cache": str(CN_CACHE), "items": []}
    ok_all = True
    for raw in a.names:
        m = re.search(r"c(\d+)_(\d+)", raw)
        if not m:
            rep["items"].append({"name": raw, "status": "bad-name"})
            ok_all = False
            continue
        code = "c%s_%s" % (m.group(1), m.group(2))
        dst = out_dir / ("si_%s_s_uc_tex.png" % code)
        if dst.exists() and not a.force:
            rep["items"].append({"code": code, "status": "exists", "path": str(dst)})
            continue
        path, why = cn_lookup(code)
        if not path:
            rep["items"].append({"code": code, "status": "miss", "why": why})
            ok_all = False
            continue
        good, info = cn_extract(path, dst)
        rep["items"].append({"code": code, "status": "ok" if good else "fail",
                             "path": str(dst) if good else None, "info": info,
                             "source": str(path)})
        ok_all &= good
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="代号，如 c019_00 或 si_c019_00_s")
    ap.add_argument("--root", default="", help="国际服客户端根（含 com.shiftup.patch）")
    ap.add_argument("--bucket", default="dp")
    ap.add_argument("-o", "--out", default=str(SI_DIR))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--cn", action="store_true",
                    help="走国服单角色小包（需该角色图标已在本地缓存；国服独有角色只能走这条）")
    a = ap.parse_args()

    if a.cn:
        return run_cn(a)

    if a.root:
        root, root_src = a.root, "arg"
    else:
        root, root_src = guess_intl_root()
    if not root:
        print(json.dumps({"error": "定位不到国际服客户端根，请用 --root 指定（含 com.shiftup.patch）"},
                         ensure_ascii=False))
        return 2
    nk.intl_root(root)                                # 提前校验

    key = si_bundle_key(root, a.bucket)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="getsi_"))
    try:
        data, segs = nk.intl_fetch(root, a.bucket, key)
        bundle = tmp / "si.bundle"
        bundle.write_bytes(data)
        rep = {"root": root, "rootSource": root_src, "bundle": key, "segs": segs, "items": []}
        for raw in a.names:
            sprite = norm_name(raw)
            dst = out_dir / (sprite + "_intl.png")
            if dst.exists() and not a.force:
                rep["items"].append({"sprite": sprite, "status": "exists", "path": str(dst)})
                continue
            stage = tmp / sprite
            stats = nk.export(str(bundle), str(stage), only=sprite)
            hits = sorted(stage.glob("*.png"))
            exact = [h for h in hits if h.stem == sprite]
            if exact:
                hits = exact
            if not hits:
                rep["items"].append({"sprite": sprite, "status": "miss", "stats": stats})
                continue
            shutil.move(str(hits[0]), str(dst))
            rep["items"].append({"sprite": sprite, "status": "ok", "path": str(dst),
                                 "bytes": dst.stat().st_size, "stats": stats})
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if all(i["status"] in ("ok", "exists") for i in rep["items"]) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
