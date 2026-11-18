# -*- coding: utf-8 -*-
"""最小冻结用例：按 NT_MODE 逐项复现 main.py 的参数，定位窗口不可见的原因

NT_MODE 取值:
  html      纯 html 字符串，显式 gui=edgechromium（已知可用）
  nogui     html 字符串，但 start() 不指定 gui（复现 main.py 的调用方式）
  file      从 _MEIPASS 读 index.html 作为 url
  api       在 html 模式上挂 js_api
  full      完全照搬 main.py 的参数组合
"""
import os
import sys
import traceback

MODE = os.environ.get("NT_MODE", "html")
LOG = os.path.join(os.path.dirname(sys.executable), "nt.log")


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


class Api:
    def __init__(self):
        self._win = None
        self._cache = None

    def bind(self, win):
        self._win = win

    def ping(self):
        return "pong"

    def load_table(self):
        return {"ok": True, "data": {"slots": []}}


def main():
    log("mode=%s frozen=%s" % (MODE, getattr(sys, "frozen", False)))
    import webview

    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    html = "<h1 style='color:red'>hello</h1>"
    url = html
    if MODE in ("file", "full"):
        url = os.path.join(base, "ui", "index.html")
        log("file exists=%s" % os.path.exists(url))

    kw = dict(width=600, height=400)
    if MODE == "full":
        kw = dict(width=1440, height=920, min_size=(1100, 720),
                  background_color="#0f1117", frameless=False, easy_drag=False)

    api = Api()
    win = webview.create_window("NT-" + MODE, url,
                                js_api=api if MODE in ("api", "full") else None, **kw)
    api.bind(win)
    win.events.shown += lambda: log("SHOWN event fired")
    log("entering start()")

    if MODE == "nogui":
        webview.start()
    else:
        webview.start(gui="edgechromium")
    log("start() returned")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXCEPTION:\n" + traceback.format_exc())
