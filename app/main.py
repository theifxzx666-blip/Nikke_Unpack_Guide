# -*- coding: utf-8 -*-
"""取件库客户端 · 主程序

pywebview + WebView2（pywebview 为 BSD-3-Clause，https://github.com/r0x0r/pywebview）。
UI 在 ui/index.html，Python 只做数据与执行。
所有耗时操作（拆包、渲染）走子进程，主进程不 import UnityPy。
第三方来源与许可见仓库根 THIRD_PARTY_NOTICES.md。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback

import webview

# 本机路径一律不写死：换一台 Windows 电脑时目录盘符会变。
# 资源库解析顺序：环境变量 NK_LIB → 同目录 settings.json → 从程序目录逐级向上自动探测。
# 工具目录与 UnityPy 解释器同样可覆盖：NK_TOOLS / NK_PY_ASSET。
DEFAULT_LIB = ""
CFG_NAME = "settings.json"
LIB = DEFAULT_LIB


def app_dir():
    """程序所在目录：打包后是 exe 旁边，开发时是脚本目录"""
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))


def detect_tools():
    """从程序目录逐级向上找含 nk.py 的 tools/，适应「exe 放在仓内任意层」的用法"""
    cur = app_dir()
    for _ in range(6):
        cand = os.path.join(cur, "tools")
        if os.path.isfile(os.path.join(cand, "nk.py")):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


_ALIAS = None


def alias_map():
    """代号↔中文名：读 app/ui/_alias.json（由 00_索引\角色代号中文名对照表.xlsx 生成）"""
    global _ALIAS
    if _ALIAS is None:
        _ALIAS = {"code2names": {}, "name2codes": {}}
        try:
            with open(os.path.join(app_dir(), "ui", "_alias.json"), encoding="utf-8") as f:
                d = json.load(f)
            _ALIAS = {"code2names": d.get("code2names", {}),
                      "name2codes": d.get("name2codes", {})}
        except Exception:
            pass
    return _ALIAS


def scope_terms(keyword):
    """范围关键字展开成 {text:[...], codes:{int}}：输入中文名补代号，输入代号补中文名"""
    q = (keyword or "").strip()
    if not q:
        return None
    a = alias_map()
    if re.fullmatch(r"[cC]?\d{1,5}", q):          # 输入的是代号：只按数值精确匹配，不做文本前缀
        n = str(int(re.sub(r"\D", "", q)))
        text = [nm.lower() for nm in a["code2names"].get(n, [])]
        codes = {int(n)}
    else:                                          # 输入的是名字：文本匹配 + 该名字的全部代号
        text = [q.lower()]
        codes = {int(x) for x in a["name2codes"].get(q, []) + a["name2codes"].get(q.lower(), [])}
    return {"text": text, "codes": codes}


# 文件名里的角色代号：前后不能紧贴字母数字，避免撞上 hash 片段
CODE_RE = re.compile(r"(?<![0-9a-z])[cC](\d{1,5})(?![0-9a-z])")


def scope_hit(rel, terms):
    """rel 是否命中范围。terms 为 None 表示不限范围"""
    if not terms:
        return True
    low = rel.lower()
    if any(t in low for t in terms["text"]):
        return True
    if terms["codes"]:
        found = {int(x) for x in CODE_RE.findall(rel)}
        return bool(found & terms["codes"])
    return False


def cfg_path():
    return os.path.join(app_dir(), CFG_NAME)


def load_cfg():
    p = cfg_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cfg(cfg):
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# 工具目录：环境变量 → 向上探测 → 仓内 app/ 的上一级（都没有时体检会显示未命中）
TOOLS = os.environ.get("NK_TOOLS", "").strip() or detect_tools() \
    or os.path.join(os.path.dirname(app_dir()), "tools")
# 跑 UnityPy 的解释器：环境变量 → settings.json 的 py_asset → 当前解释器
# （GUI 用 pywebview 环境，拆包用 UnityPy 环境，两者常常不是同一个 python）
PY_ASSET = os.environ.get("NK_PY_ASSET", "").strip() \
    or str(load_cfg().get("py_asset", "") or "") or sys.executable


def valid_lib(p):
    """一个目录要算「资源库」，至少得有 00_索引，外加 10_用户层 或 20_开发层"""
    if not p or not os.path.isdir(os.path.join(p, "00_索引")):
        return False
    return os.path.isdir(os.path.join(p, "10_用户层")) \
        or os.path.isdir(os.path.join(p, "20_开发层"))


def detect_lib():
    """从程序目录逐级向上找 00_资源库，适配「exe 和资源库放在同一批目录里」的用法"""
    cur = app_dir()
    for _ in range(6):
        cand = os.path.join(cur, "00_资源库")
        if valid_lib(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


def resolve_lib():
    """按优先级决定用哪个资源库，返回 (路径, 来源说明)"""
    env = os.environ.get("NK_LIB", "").strip()
    if valid_lib(env):
        return env, "环境变量"
    saved = load_cfg().get("lib", "")
    if valid_lib(saved):
        return saved, "设置文件"
    found = detect_lib()
    if found:
        return found, "自动探测"
    return "", "未配置"



def resource_path(rel):
    """打包后从 _MEIPASS 取资源，开发时从脚本目录取"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


UI = resource_path(os.path.join("ui", "index.html"))


def prepare_env():
    """打包环境的两个坑，必须在 import webview 之前/启动早期处理：

    1. --windowed 打包时 sys.stdout 为 None，pywebview 内部一旦 print 就会失败，
       表现为「进程活着但没有窗口」。所以这里始终用 console 打包，再把控制台
       窗口隐藏掉，视觉上与窗口程序一致。
    2. 隐藏窗口要用 Win32，控制台句柄在打包和源码两种情况下都存在。
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass



def latest_slot_table():
    d = os.path.join(LIB, "00_索引")
    if not os.path.isdir(d):
        return None
    fs = sorted(f for f in os.listdir(d) if f.startswith("取件表_") and f.endswith(".json"))
    return os.path.join(d, fs[-1]) if fs else None


class Api:
    def __init__(self):
        self._win = None
        self._cache = None
        self._lib_source = "未配置"

    def bind(self, win):
        self._win = win

    # ---------- 资源库位置 ----------
    def status(self):
        return {"lib": LIB, "ok": valid_lib(LIB), "source": self._lib_source}

    def _pick_dir(self):
        """弹目录选择框。pywebview 新旧版本常量名不同，两个都试。"""
        const = None
        fd = getattr(webview, "FileDialog", None)
        if fd is not None and hasattr(fd, "FOLDER"):
            const = fd.FOLDER
        else:
            const = getattr(webview, "FOLDER_DIALOG", None)
        r = self._win.create_file_dialog(const)
        if not r:
            return ""
        return r[0] if isinstance(r, (list, tuple)) else str(r)

    def pick_lib(self, path=""):
        """设置资源库目录：传了 path 就直接用，没传就弹框选"""
        global LIB
        p = (path or "").strip() or self._pick_dir()
        if not p:
            return {"ok": False, "error": "未选择目录"}
        p = p.replace("\\", "/").rstrip("/")
        if not valid_lib(p):
            return {"ok": False, "error": "这个目录不像资源库（缺少 00_索引，或没有 10_用户层 / 20_开发层）"}
        LIB = p
        self._lib_source = "手动指定"
        self._cache = None
        cfg = load_cfg()
        cfg["lib"] = p
        save_cfg(cfg)
        return {"ok": True, "lib": p}

    # ---------- 数据 ----------
    def load_table(self):
        p = latest_slot_table()
        if not p:
            return {"ok": False, "error": "未找到取件表，请先运行 slot_build.py"}
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            data["file"] = os.path.basename(p)
            self._cache = data
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

    def _row(self, key):
        """按 id 找槽位，找不到再用 slot 名兜底（兼容旧取件表）"""
        if not self._cache:
            return None
        for s in self._cache["slots"]:
            if s.get("id") == key:
                return s
        for s in self._cache["slots"]:
            if s.get("slot") == key:
                return s
        return None

    def _target(self, row):
        """槽位对应的磁盘路径：可能是目录，也可能是单个文件"""
        return os.path.join(LIB, row["local"]) if row.get("local") else ""

    def list_files(self, slot, limit=400, keyword=""):
        """列出某个槽位下的文件（相对路径）。keyword 按相对路径过滤，先筛后截断"""
        row = self._row(slot)
        if not row:
            return []
        root = self._target(row)
        if not root or not os.path.exists(root):
            return []

        exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".xlsx", ".csv")
        terms = scope_terms(keyword)

        def hit(rel):
            return scope_hit(rel, terms)

        # 槽位直接指向单个成品文件
        if os.path.isfile(root):
            name = os.path.basename(root)
            if not root.lower().endswith(exts) or not hit(name):
                return []
            return [{"name": name, "rel": name, "size": os.path.getsize(root)}]

        out = []
        for dp, _, fs in os.walk(root):
            for f in fs:
                if not f.lower().endswith(exts):
                    continue
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root).replace("\\", "/")
                if not hit(rel):
                    continue
                out.append({"name": f, "rel": rel, "size": os.path.getsize(full)})
                if len(out) >= limit:
                    return out
        return out

    def preview(self, slot, rel):
        """返回本地图片的 file:// URL（pywebview 可直接加载）"""
        row = self._row(slot)
        if not row:
            return ""
        root = self._target(row)
        p = root if os.path.isfile(root) else os.path.join(root, rel.replace("/", os.sep))
        return "file:///" + p.replace("\\", "/") if os.path.exists(p) else ""

    def open_folder(self, slot):
        row = self._row(slot)
        if not row:
            return False
        p = self._target(row)
        if os.path.isdir(p):
            os.startfile(p)
            return True
        if os.path.isfile(p):
            os.startfile(os.path.dirname(p))
            return True
        return False

    def pick_folder(self):
        """弹目录选择框，返回绝对路径"""
        try:
            return self._pick_dir()
        except Exception:
            return ""

    def export_slot(self, slot, dest, keyword=""):
        """把槽位下的文件复制到目标目录，按槽位名建子目录；keyword 只导范围内的。
        返回 {ok, count, bytes, dest} 或 {ok:False, error}"""
        return self.export_many([slot], dest, keyword)

    def export_scene(self, scene, dest, keyword=""):
        """按场景批量取件：一个场景下的所有可提取槽位"""
        if not self._cache:
            return {"ok": False, "error": "取件表未加载"}
        keys = [s.get("id") or s["slot"] for s in self._cache["slots"]
                if s["scene"] == scene and s["mode"] != "unavailable"]
        if not keys:
            return {"ok": False, "error": "该场景没有可提取槽位"}
        return self.export_many(keys, dest, keyword)

    def export_many(self, slots, dest, keyword=""):
        if not self._cache:
            return {"ok": False, "error": "取件表未加载"}
        jobs = []
        for slot in slots:
            row = self._row(slot)
            if not row:
                continue
            src = self._target(row)
            if not src or not os.path.exists(src):
                continue
            jobs.append((row.get("slot") or slot, src))
        if not jobs:
            return {"ok": False, "error": "没有可复制的文件"}

        # 先排计划：目录展开成文件清单，单文件槽位直接入列；keyword 只留范围内的
        terms = scope_terms(keyword)
        plan = []
        for slot, src in jobs:
            if os.path.isfile(src):
                if scope_hit(os.path.basename(src), terms):
                    plan.append((slot, os.path.dirname(src), src))
                continue
            for dp, _, fs in os.walk(src):
                for f in fs:
                    fp = os.path.join(dp, f)
                    if not scope_hit(os.path.relpath(fp, src).replace("\\", "/"), terms):
                        continue
                    plan.append((slot, src, fp))
        total = len(plan)
        if not total:
            return {"ok": False, "error": "槽位为空"}

        done = nbytes = 0
        try:
            for slot, src, fp in plan:
                rel = os.path.relpath(fp, src)
                to = os.path.join(dest, slot.replace("/", os.sep), rel)
                os.makedirs(os.path.dirname(to), exist_ok=True)
                shutil.copy2(fp, to)
                nbytes += os.path.getsize(to)
                done += 1
                if done % 15 == 0 or done == total:
                    self._push(done, total, os.path.basename(fp))
        except Exception as e:
            return {"ok": False, "error": f"复制中断于 {done}/{total}：{e}"}

        self._push(total, total, "完成")
        return {"ok": True, "count": done, "mb": round(nbytes / 1048576, 2), "dest": dest}

    def _push(self, done, total, name):
        try:
            if self._win:
                self._win.evaluate_js(
                    f"window.__prog && window.__prog({done},{total},{json.dumps(name, ensure_ascii=False)})")
        except Exception:
            pass

    def doctor(self):
        """自检：关键依赖与客户端是否存在"""
        checks = []
        checks.append(("取件表", bool(latest_slot_table())))
        checks.append(("资源库", os.path.isdir(LIB)))
        checks.append(("nk.py", os.path.exists(os.path.join(TOOLS, "nk.py"))))
        checks.append(("UnityPy 解释器", os.path.exists(PY_ASSET)))
        return [{"name": n, "ok": ok} for n, ok in checks]


def crash_log_path():
    """崩溃日志位置：打包后放 exe 同目录，开发时放脚本目录"""
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "crash.log")


def main():
    global LIB
    LIB, src = resolve_lib()

    if os.environ.get("NK_TRACE") == "1":
        print("[trace] frozen =", getattr(sys, "frozen", False), flush=True)
        print("[trace] _MEIPASS =", getattr(sys, "_MEIPASS", "(无)"), flush=True)
        print("[trace] UI =", UI, "exists =", os.path.exists(UI), flush=True)
        print("[trace] LIB =", LIB, "来源 =", src, flush=True)
        print("[trace] guilib =", webview.guilib, flush=True)

    api = Api()
    api._lib_source = src
    win = webview.create_window(
        "取件库 · NIKKE",
        UI,
        js_api=api,
        width=1440,
        height=920,
        min_size=(1100, 720),
        background_color="#0f1117",
        frameless=False,
        easy_drag=False,
    )
    api.bind(win)
    if os.environ.get("NK_TRACE") == "1":
        print("[trace] create_window 返回 =", win, flush=True)
        print("[trace] 即将进入 start()", flush=True)
    webview.start(debug=os.environ.get("NK_DEBUG") == "1")
    if os.environ.get("NK_TRACE") == "1":
        print("[trace] start() 已返回，窗口已关闭", flush=True)


if __name__ == "__main__":
    # 打包成 --windowed 后没有控制台，异常会静默消失。落盘才能在出问题时定位。
    prepare_env()
    try:
        main()
    except Exception:
        msg = traceback.format_exc()
        with open(crash_log_path(), "w", encoding="utf-8") as f:
            f.write(msg)
        raise
