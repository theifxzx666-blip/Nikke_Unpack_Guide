# 第三方组件与参考来源

本文件登记本仓库使用、调用或参考过的第三方组件、工具与资料，并说明参考范围。据现有记录，未列出的实现与文档由本仓库作者编写；如发现遗漏或表述不当，请提交 issue 指正。

## 一、原创范围

本仓库作者编写的部分：

- 四场景判定方法（容器形态 × 平台）与取件链路；
- `NKDB` / `CIDX` 的读取实现、`store.cdb` 块级拼装与校验；
- 国服「对象名 → 缓存路径」索引方案与分片 subprocess 实现；
- 批量取件、预检、自检指标与效率实测；
- 采集工作流、落盘命名与全部文档。

格式知识来自对客户端文件的实测与下列公开资料。**本仓库不对游戏格式、第三方工具或游戏资源主张著作权。**

## 二、运行时依赖

以下组件通过 pip 安装，不随本仓库分发。

| 组件 | 版本 | 许可 | 用途 | 主页 |
| :--- | :--- | :--- | :--- | :--- |
| UnityPy | 1.25.4 | MIT | 解析 UnityFS bundle，导出 Texture2D / Sprite / AudioClip / TextAsset / 模型 | https://github.com/K0lb3/UnityPy |
| zstandard | 0.25.0 | BSD-3-Clause | `store.cdb` 块级 zstd 解压 | https://github.com/indygreg/python-zstandard |
| Pillow | 12.3.0 | HPND | 图像落盘与尺寸校验 | https://github.com/python-pillow/Pillow |
| pycryptodome | 3.24.0 | BSD / Public Domain | `NKDB` 的 AES-128-OFB 解密 | https://www.pycryptodome.org |
| pywebview | 未锁定 | BSD-3-Clause | `app/` 桌面客户端 GUI | https://github.com/r0x0r/pywebview |
| PyInstaller | 未锁定 | GPL-2.0-or-later，含打包例外 | `app/` 生成 exe | https://pyinstaller.org/en/stable/license.html |

版本以 [`tools/requirements.txt`](tools/requirements.txt) 与构建环境为准。各组件版权归其作者，使用须遵守各自许可。

其他运行时组件：

| 组件 | 许可 | 用途 | 主页 |
| :--- | :--- | :--- | :--- |
| Python 3.13 | PSF-2.0 | 运行时 | https://www.python.org |
| SQLite（经 Python `sqlite3`） | Public Domain | 国服对象名索引 | https://www.sqlite.org |
| Android SDK Platform-Tools（adb） | Android SDK 条款 | 设备取件 | https://developer.android.com/tools/releases/platform-tools |
| .NET Runtime 8.0 | MIT | NAU 运行所需 | https://dotnet.microsoft.com/download/dotnet/8.0 |
| Microsoft Edge WebView2 Runtime | Microsoft 软件许可 | `app/` 界面渲染宿主 | https://developer.microsoft.com/microsoft-edge/webview2/ |

## 三、外部工具

以下工具**不随本仓库分发**，仅在文档中说明调用方式。

| 工具 | 版本 | 作者 / 来源 | 许可 | 用途 |
| :--- | :--- | :--- | :--- | :--- |
| NAU（NikkeAssetUnpacker） | 1.0.0 | 社区资料记为 **bingle**；发布页 <https://nikke-modding-wiki.vercel.app/downloads/NAU.rar>；署名见 [Nikke-DB 致谢](https://nikke-db.pages.dev/credits) 与 [Doro_Repacker_EX 致谢](https://github.com/asd790320224/Doro_Repacker_EX) | 未声明开源许可 | `NKAB` 解密；社区记录中 v3 与 v4 解密由 bingle 实现（v4 与 Dani 合作）。本仓库以子进程调用 `NAU.exe d -i <in> -o <out>` |
| Spine Runtimes（`spine-player.js` 4.1 / 4.0） | 4.1.20 / 4.0.47 | © Esoteric Software | [Spine Runtimes License](https://esotericsoftware.com/spine-runtimes-license) | 角色与敌人 Spine 的渲染；运行时位于资源库侧，不在本仓库 |

## 四、格式与资料参考

| 来源 | 许可 | 参考范围 | 链接 |
| :--- | :--- | :--- | :--- |
| MemoryPack（Cysharp） | MIT | `.mpk` 为 MemoryPack 二进制序列化。本仓库按 C# 类型定义还原字段顺序，用 Python 独立实现解码，**未复制其代码** | https://github.com/Cysharp/MemoryPack |
| Unity Addressables / UnityFS | Unity Technologies 的公开格式 | 清单结构与 bundle 头部的判定依据；解析实现基于对客户端文件的实测 | https://docs.unity3d.com/Packages/com.unity.addressables@latest |
| NIKKE modding 社区资料 | 见各自页面 | `NKAB` 版本演进的公开讨论与署名线索；未复制代码 | https://nikke-modding-wiki.vercel.app/ |
| Chrome DevTools Protocol（Chromium 项目） | Chromium 项目条款 | 截图与渲染驱动的协议依据；`app/ui/_shot.js` 自行实现 CDP 客户端，未引入第三方库 | https://chromedevtools.github.io/devtools-protocol/ |

## 五、交互与选型参考

| 对象 | 参考范围 | 是否使用其代码 | 链接 |
| :--- | :--- | :--- | :--- |
| ArcanaHelper（`ArcanaHelper-V1.1.2.exe`） | 仅参考「先限定范围才能继续」的分步交互流程，见 [`docs/08-取件库客户端规格.md`](docs/08-取件库客户端规格.md) 第八节 | 否 | 作者与发布页本仓库未记录，**待补** |
| eel | 技术选型对照，评估后未采用（依赖本机 Chrome，无法封装） | 否 | https://github.com/python-eel/Eel |

## 六、致谢

感谢以下作者与社区的工作，本方案得以在格式解析与渲染环节少走弯路：

- **K0lb3** — UnityPy；
- **Gregory Szorc** — python-zstandard；
- **Pillow 团队**、**Legrandin** — Pillow、PyCryptodome；
- **Roman Sirokov** — pywebview；**PyInstaller 团队** — 打包工具；
- **Cysharp** — MemoryPack 格式与实现；
- **Esoteric Software** — Spine Runtimes；
- **bingle** — NAU；**Nikke-DB** 与 NIKKE modding 社区 — 公开资料与署名线索；
- **Shift Up、Level Infinite、Tencent** — 作品与资源版权方。

## 七、许可状态与纠错

- 本仓库文档采用 [CC BY-NC-SA 4.0](LICENSE)；**代码部分尚未单独声明开源许可**，如他人需复用代码，请先联系作者确认。
- 若发现未标注的来源或表述不当，请提交 issue，将在下次修订中补充或更正。
