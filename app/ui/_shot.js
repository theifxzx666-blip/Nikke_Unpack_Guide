// 用 CDP 对 UI 截图：加载 -> 点场景 -> 点行 -> 截图
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");
const url = require("url");

const ROOT = __dirname;
// Chrome 位置按「环境变量 → 常见安装路径」找，不写死某一台机器
const CHROME = process.env.NK_CHROME || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Google/Chrome/Application/chrome.exe"),
].filter(Boolean).find(p => fs.existsSync(p)) || "";
if (!CHROME) {
  console.error("未找到 Chrome：设 NK_CHROME 指向 chrome.exe 后再跑");
  process.exit(2);
}
const PORT = 9345, SRV = 8770;
const OUT = process.argv[2] || path.join(ROOT, "_shot.png");
const ACTION = process.argv[3] || "scene";   // scene | row
const SCENE_IDX = parseInt(process.argv[4] || "0", 10);   // 第几个场景，从 0 起

const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css", ".json": "application/json", ".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg" };

const sleep = ms => new Promise(r => setTimeout(r, ms));

function serve() {
  const s = http.createServer((req, res) => {
    let p = decodeURIComponent(url.parse(req.url).pathname);
    if (p === "/") p = "/index.html";
    const fp = path.join(ROOT, p);
    fs.readFile(fp, (e, b) => {
      if (e) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream" });
      res.end(b);
    });
  });
  return new Promise(r => s.listen(SRV, "127.0.0.1", () => r(s)));
}

async function wsUrl() {
  for (let i = 0; i < 60; i++) {
    try {
      const j = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
      if (j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl;
    } catch {}
    await sleep(150);
  }
  throw new Error("no devtools");
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.p = new Map(); this.errs = [];
    ws.onmessage = e => { const m = JSON.parse(e.data);
      if (m.method === "Runtime.exceptionThrown") {
        const d = m.params.exceptionDetails;
        this.errs.push((d.exception && d.exception.description) || d.text);
      }
      if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
        this.errs.push("console: " + m.params.args.map(a => a.value ?? a.description).join(" "));
      }
      if (m.id && this.p.has(m.id)) { const { r, j } = this.p.get(m.id); this.p.delete(m.id);
        m.error ? j(new Error(JSON.stringify(m.error))) : r(m.result); } }; }
  send(method, params = {}, sessionId) {
    const id = ++this.id; const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    this.ws.send(JSON.stringify(msg));
    return new Promise((r, j) => this.p.set(id, { r, j }));
  }
}

(async () => {
  const srv = await serve();
  const chrome = spawn(CHROME, ["--headless=new", "--no-sandbox", "--enable-unsafe-swiftshader",
    "--hide-scrollbars", `--remote-debugging-port=${PORT}`,
    "--window-size=1440,920",
    "--user-data-dir=" + path.join(require("os").tmpdir(), "cdp-shot-" + Date.now()),
    "about:blank"], { stdio: "ignore" });
  try {
    const w = new WebSocket(await wsUrl());
    await new Promise((r, j) => { w.onopen = r; w.onerror = j; });
    const c = new CDP(w);
    const { targetInfos } = await c.send("Target.getTargets");
    const page = targetInfos.find(t => t.type === "page");
    const { sessionId: S } = await c.send("Target.attachToTarget", { targetId: page.targetId, flatten: true });
    await c.send("Page.enable", {}, S);
    await c.send("Runtime.enable", {}, S);
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 920, deviceScaleFactor: 1, mobile: false }, S);
    await c.send("Page.navigate", { url: `http://127.0.0.1:${SRV}/index.html` }, S);

    // 等场景按钮真的渲染出来再点，固定 sleep 会被数据加载耗时打败
    for (let i = 0; i < 60; i++) {
      const r = await c.send("Runtime.evaluate", {
        expression: "document.querySelectorAll('.sc').length", returnByValue: true
      }, S);
      if ((r.result.value || 0) > 0) break;
      await sleep(200);
    }
    await sleep(300);

    // 点指定的场景
    await c.send("Runtime.evaluate", {
      expression: `document.querySelectorAll('.sc')[${SCENE_IDX}].click()`
    }, S);
    await sleep(600);
    if (ACTION === "row") {
      await c.send("Runtime.evaluate", { expression: `document.querySelectorAll('tbody tr')[0].click()` }, S);
      await sleep(1600);
    }
    const { data } = await c.send("Page.captureScreenshot", { format: "png" }, S);
    fs.writeFileSync(OUT, Buffer.from(data, "base64"));
    console.log("截图:", OUT);

    // 把页面内的报错和关键状态一并打出来，省得靠猜
    const st = await c.send("Runtime.evaluate", {
      expression: `(()=>{const b=document.querySelector('.sc');
        const has=!!b.onclick; let err=null;
        try{ b.click(); }catch(e){ err=e.message; }
        return JSON.stringify({hasClick:has, clickErr:err,
          scene:(typeof scene!=='undefined'?scene:'undef'),
          rows:document.querySelectorAll('tbody tr').length,
          scenes:[...document.querySelectorAll('.sc')].map(x=>x.textContent.trim().replace(/\\s+/g,' '))})})()`,
      returnByValue: true
    }, S);
    console.log("页面状态:", st.result.value);
    if (c.errs.length) console.log("页面报错:\n" + c.errs.join("\n"));
    w.close();
  } finally { chrome.kill(); srv.close(); }
})().catch(e => { console.error(e); process.exit(1); });
