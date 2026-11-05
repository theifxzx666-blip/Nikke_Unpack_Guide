# NIKKE 客户端拆包方案

从客户端取资源的一套工程方案，覆盖四个场景：**国际服 / 国服 × PC / 安卓**。
文中数字均为实测值，出处标在对应文档。

技能入口是 [SKILL.md](SKILL.md)；给 AI 的操作规范是 [AGENTS.md](AGENTS.md)。

## 为什么是四个场景

不是四套方案，是 **两个正交维度**：**容器形态**决定清单与数据体格式（硬分叉），**端**只决定字节怎么搬。

| | 七桶形态 | 缓存形态 |
| :--- | :--- | :--- |
| **PC** | `catalog.ndb`(NKDB) + `store.cdb`(CIDX)，本地直读 | Addressables JSON + UnityCache，本地直读 |
| **安卓** | 同上，`adb exec-out dd` 定点读 | 同上，`adb pull` 整文件 |
| **谁在用** | 国际服（PC/安卓）；国服的七桶客户端 | 国服 WeGame 版；国服安卓 |

容器形态**与服名不一一对应**，所以先判容器，再判端。判错的代价不对称：往错的方向找，会卡在第一步而且毫无提示。

## 五分钟上手

```bash
# 环境
python -c "import UnityPy, zstandard, PIL, Crypto; print('ok')"
export MSYS_NO_PATHCONV=1          # Git Bash 调 adb 前必做

# 判场景
python tools/nk.py doctor --scene intl-pc --root "D:/.../NIKKEG"

# 先确认资源在哪个服：两服命中数 + 类型构成 + 一句结论（0.4 s）
python tools/nk.py locate "marian" --intl-root "D:/.../NIKKEG" --cn-root "E:/.../nikke_Data"

# 国际服 PC：解七桶清单 → 查键 → 取包+导出（一条命令）
python tools/nk.py scan   --scene intl-pc --root "D:/.../NIKKEG"
python tools/nk.py find   --scene intl-pc --root "D:/.../NIKKEG" --bucket dp "c010_00"
python tools/nk.py pull   --scene intl-pc --root "D:/.../NIKKEG" --bucket dp "<完整键>" -o x/

# 批量：一个进程吃整份键表（20 件 3.2 s；逐件起进程要 52.4 s）
python tools/nk.py batch  --scene intl-pc --root "D:/.../NIKKEG" --bucket dp keys.txt -o out/ --jobs 4

# 国服：建索引 → 按对象名取包 → 导出
python tools/nk.py cnindex --root "<cache 根>" -o build/cn_index.sqlite --jobs 4
python tools/nk.py cnget   --root "<cache 根>" "<32hex>" -o x.bundle
```

单件 2.6 s 里 2.05 s 是解释器与 `import UnityPy` 的固定成本，所以**批量跑才快**：
同一批 20 件，逐件起进程 52.4 s、`batch` 7.4 s。数字与瓶颈分析见
[docs/05-效率实测.md](docs/05-效率实测.md)。

## 当成技能用

本仓库根目录就是技能包（`SKILL.md` + `docs/`），安装方式二选一：

```bash
# 方式一：软链（推荐，改仓库即时生效，不产生副本）
# Windows 管理员 PowerShell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.workbuddy\skills\nikke-unpack" `
         -Target "F:\Codex\Nikke\01_母体\B_客户端资源\02_Skills\Nikke_Unpack_Guide"

# 方式二：直接引用
# 在任意项目里 `git clone` 本仓库，把路径告诉 Agent 即可
```

装上之后，说「拆包」「取素材」「这个客户端资源在哪」就会命中本技能。

## 四场景实测基数

| 场景 | 资源根 | 体量 | 取件粒度 |
| :--- | :--- | :--- | :--- |
| 国际服 PC | `<安装目录>/Unity/com_proximabeta_NIKKE/com.shiftup.patch` | 七桶 `store.cdb` 28.3 GB | 块 |
| 国际服安卓 | `/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch` | core `store.cdb` 5.34 GB | 块 |
| 国服 PC（WeGame） | `<安装目录>/nikke_Data/runtime_data` | 22,210 个 `__data` / 8.46 GB | 整文件 |
| 国服安卓 | `/sdcard/Android/data/com.tencent.nikke/files` | UnityCache + 177 组清单 | 整文件 |

版本：国际服 153.6.10（code 1530610）· 国服 22.1.1（code 2201001）。数字随版本变，方法不变。

## 四处真差异

| # | 项 | 七桶形态 | 缓存形态 |
| :-: | :--- | :--- | :--- |
| 1 | 清单 | 自研 `NKDB`（AES-128-OFB，密钥在偏移 8） | Unity Addressables 明文 JSON |
| 2 | 数据体 | `store.cdb` + `CIDX` 索引，块级 zstd | Unity Cache 目录树，整包 |
| 3 | 文本表 | `.lsc`，**NKDB 加密** | `.lss`，**明文 SQLite** |
| 4 | 取件 | 块级，要 dd 拼装与连续性校验 | 整文件，难点在定位 |

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [docs/00-场景矩阵.md](docs/00-场景矩阵.md) | 四场景判定表、基数、链路、五个坑 |
| [docs/samples.md](docs/samples.md) | 每场景最小采集样本与自检数字 |
| [docs/intl-pc/](docs/intl-pc/README.md) | 国际服 PC：路径、取件、43 类结果、场景装配 |
| [docs/intl-android/](docs/intl-android/README.md) | 国际服安卓：adb 取件、三条硬约束、权限 |
| [docs/cn-pc/](docs/cn-pc/README.md) | 国服 PC：清单→缓存定位、明文缓存、NKAB 判据 |
| [docs/cn-android/](docs/cn-android/README.md) | 国服安卓：UnityCache、明文 lss、与 PC 差异 |
| [docs/common/](docs/common/01-overview.md) | 六阶段、43 类键规律、落盘命名、工具契约、容器字节结构、取件算法 |
| [SKILL.md](SKILL.md) / [AGENTS.md](AGENTS.md) | 技能入口 / 给 AI 的操作规范 |

## 已知限制

| 项 | 结论 |
| :--- | :--- |
| 低清 `(sd)` 缺块 | 国际服 `.idx` 100% 覆盖物理字节，缺的块物理不存在，只能靠游戏内按需下载补 |
| 静态表（关卡/数值） | 国际服 PC 路径不存在；安卓在 `cache/StaticData.pack`，双层 AES 在部分版本解不开 |
| 动态头像框 | 国际服 PC 无该族；安卓有 |
| 国服定位 | 清单与缓存路径无确定映射，必须建对象名索引反查 |
| 工具 | 子命令契约见 [docs/common/04-tooling.md](docs/common/04-tooling.md)，`tools/nk.py` 实现了 doctor/scan/locate/find/get/pull/batch/cnindex/cnget/export |
| 效率 | [docs/05-效率实测.md](docs/05-效率实测.md)：批量比逐件快 16 倍（100 件约 52 倍），附瓶颈分解与剩余优化项 |

## 免责

仅用于个人研究、资料存档与资讯整理。不提供游戏本体，不提供可运行的修改版客户端，不用于商业用途。

所有资源版权归 Shift Up 及相关权利方所有。请勿再分发提取出的美术与音频资源。
