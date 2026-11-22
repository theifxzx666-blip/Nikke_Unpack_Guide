# NIKKE 客户端拆包方案

面向《胜利女神：NIKKE》客户端的资源提取工程方案，覆盖国际服 PC、国际服安卓、国服 PC（WeGame）与国服安卓四个场景。文中数值均为实测值，出处见对应文档。

| 文件 | 用途 |
| :--- | :--- |
| [`SKILL.md`](SKILL.md) | 技能入口 |
| [`AGENTS.md`](AGENTS.md) | AI 操作规范 |

## 1. 方案模型

### 1.1 两个正交维度

四个场景并非四套独立方案，而由两个正交维度组合而成：

- **容器形态**：决定清单与数据体的格式，属硬性分叉；
- **平台**：仅决定字节的搬运方式。

判定顺序为**先容器、后平台**。容器形态与服务器名称并非一一对应；判定方向错误时，流程会在首步停滞，且不产生任何提示。

### 1.2 场景矩阵

| 平台 | 七桶形态 | 缓存形态 |
| :--- | :--- | :--- |
| PC | `catalog.ndb`（NKDB）+ `store.cdb`（CIDX），本地直读 | Addressables JSON + UnityCache，本地直读 |
| 安卓 | 同上，`adb exec-out dd` 定点读取 | 同上，`adb pull` 整文件拉取 |
| 适用客户端 | 国际服（PC / 安卓）、国服七桶客户端 | 国服 WeGame 版、国服安卓 |

### 1.3 两类容器的四项关键差异

| 序号 | 项目 | 七桶形态 | 缓存形态 |
| :-: | :--- | :--- | :--- |
| 1 | 清单 | 自研 NKDB（AES-128-OFB，密钥位于偏移 8） | Unity Addressables 明文 JSON |
| 2 | 数据体 | `store.cdb` + CIDX 索引，块级 zstd 压缩 | Unity Cache 目录树，整包存储 |
| 3 | 文本表 | `.lsc`，NKDB 加密 | `.lss`，明文 SQLite |
| 4 | 取件 | 块级读取，需 dd 拼装并校验连续性 | 整文件读取，难点在于定位 |

## 2. 快速上手

以下命令中的 `<...>` 为占位符，需替换为实际路径。

### 2.1 环境准备

```bash
python -c "import UnityPy, zstandard, PIL, Crypto; print('ok')"
export MSYS_NO_PATHCONV=1          # Git Bash 调用 adb 前必须设置
```

### 2.2 判定场景

```bash
python tools/nk.py doctor --scene intl-pc --root "<客户端根>"
python tools/nk.py doctor --scene intl-pc --root "<客户端根>" --deep   # 容器级检查：版本、长度、校验和
```

`--deep` 目前仅覆盖 `intl-pc`。

### 2.3 确认资源所属服务器

```bash
python tools/nk.py locate "marian" --intl-root "<国际服客户端根>" --cn-root "<国服根>"
```

输出两个服务器的命中数、类型构成与结论，耗时约 0.4 s。`<国服根>` 可为 `cache`、`nikke_Data` 或安装目录。

### 2.4 国际服 PC：单件取件

```bash
python tools/nk.py scan --scene intl-pc --root "<客户端根>"
python tools/nk.py find --scene intl-pc --root "<客户端根>" --bucket dp "c010_00"
python tools/nk.py pull --scene intl-pc --root "<客户端根>" --bucket dp "<完整键>" -o x/
```

### 2.5 批量取件

```bash
python tools/nk.py batch --scene intl-pc --root "<客户端根>" --bucket dp keys.txt -o out/ --jobs 4
```

### 2.6 国服取件

```bash
python tools/nk.py cnindex --root "<缓存根>" -o build/cn_index.sqlite --jobs 4
python tools/nk.py cnget   --root "<缓存根>" "<对象名或片段>" -o x.bundle
```

### 2.7 性能特征

单件处理约 2.6 s，其中约 2.05 s 为解释器启动与 `import UnityPy` 的固定开销，因此应优先使用批量模式：同一批 20 件，逐件启动进程耗时 52.4 s，`batch` 耗时 3.2 s。实测数据与瓶颈分析见 [`docs/05-效率实测.md`](docs/05-效率实测.md)。

## 3. 安装为技能

本仓库根目录即技能包（`SKILL.md` + `docs/`），提供两种安装方式。

### 3.1 方式一：目录联接（推荐）

目录联接（Junction）使仓库改动即时生效，且不产生副本。以 Windows PowerShell 执行：

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.workbuddy\skills\nikke-unpack" `
         -Target "<本仓库的绝对路径>"
```

Junction 无需管理员权限（2026-11-13 实测）。

### 3.2 方式二：直接引用

在任意项目中 `git clone` 本仓库，并将仓库路径告知 Agent。

### 3.3 触发方式

安装后，提及「拆包」「取素材」或询问客户端资源位置时，将命中本技能。

## 4. 实测基数

| 场景 | 资源根 | 数据规模 | 取件粒度 |
| :--- | :--- | :--- | :--- |
| 国际服 PC | `<安装目录>/Unity/com_proximabeta_NIKKE/com.shiftup.patch` | 七桶 `store.cdb` 28.3 GB | 块 |
| 国际服安卓 | `/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch` | core `store.cdb` 5.34 GB | 块 |
| 国服 PC（WeGame） | `<安装目录>/nikke_Data/runtime_data` | 22,210 个 `__data`，8.46 GB | 整文件 |
| 国服安卓 | `/sdcard/Android/data/com.tencent.nikke/files` | UnityCache + 177 组清单 | 整文件 |

版本：国际服 153.6.10（code 1530610），国服 22.1.1（code 2201001）。数值随版本变化，方法不变。

## 5. 文档索引

| 文档 | 内容 |
| :--- | :--- |
| [`docs/00-场景矩阵.md`](docs/00-场景矩阵.md) | 四场景判定表、基数、链路与五个易错点 |
| [`docs/samples.md`](docs/samples.md) | 各场景最小采集样本与自检数值 |
| [`docs/intl-pc/`](docs/intl-pc/README.md) | 国际服 PC：路径、取件、43 类结果、场景装配 |
| [`docs/intl-android/`](docs/intl-android/README.md) | 国际服安卓：adb 取件、三条硬约束、权限 |
| [`docs/cn-pc/`](docs/cn-pc/README.md) | 国服 PC：清单至缓存的定位、明文缓存、NKAB 判据 |
| [`docs/cn-android/`](docs/cn-android/README.md) | 国服安卓：UnityCache、明文 lss、与 PC 的差异 |
| [`docs/common/`](docs/common/01-overview.md) | 六阶段、43 类键规律、落盘命名、工具契约、容器字节结构、取件算法 |
| [`docs/09-资源类型最佳实践.md`](docs/09-资源类型最佳实践.md) | 按资源类型：适用场景、键判据、取件步骤、验收数字 |
| [`docs/08-取件库客户端规格.md`](docs/08-取件库客户端规格.md) | 桌面客户端：选型、取件表数据模型、分期与实测问题；源码见 [`app/`](app/main.py) |
| [`SKILL.md`](SKILL.md)、[`AGENTS.md`](AGENTS.md) | 技能入口、AI 操作规范 |

## 6. 已知限制

| 项目 | 结论 |
| :--- | :--- |
| 低清 `(sd)` 缺块 | 国际服 `.idx` 覆盖 100% 物理字节，缺失块在物理上不存在，只能通过游戏内按需下载补齐 |
| 静态表（关卡 / 数值） | 客户端内不含该文件。需经 lobby API 获取 pack 与 salt1 / salt2（随版本下发），再经双层 AES 解密得到 mpk。该链路脚本不在本仓库：它属于解包后的离线加工层，与客户端取件解耦，故此处仅登记方法与入口，不附具体路径 |
| 格式变更 | 每个客户端版本应先行执行 `python tools/nk.py doctor ... --deep`；NKDB / CIDX / CBLB 的版本、长度、校验和任一项不符即直接报错，不会静默生成无效产物 |
| 动态头像框 | 仅国服安卓可用：`icons-dynamic(hd)` 共 21 组、668 帧，原生 256²；国际服 `core` / `dp` 检索 `icons-dynamic` 为 0 命中。流程见 [`docs/cn-android/动态头像框-实测.md`](docs/cn-android/动态头像框-实测.md) |
| 国服定位 | 清单与缓存路径之间不存在确定映射，必须建立对象名索引反查 |
| 工具 | 子命令契约见 [`docs/common/04-tooling.md`](docs/common/04-tooling.md)。`tools/nk.py` 已实现 `doctor` / `scan` / `locate` / `find` / `get` / `pull` / `batch` / `cnindex` / `cnget` / `export`；`tools/get_si.py` 为单件提取 SI 立绘的便捷入口 |
| 效率 | 批量较逐件快 16 倍（100 件约 52 倍），瓶颈分解与剩余优化项见 [`docs/05-效率实测.md`](docs/05-效率实测.md) |

## 7. 免责声明

本方案仅用于个人研究、资料存档与资讯整理，不提供游戏本体，不提供可运行的修改版客户端，不用于商业用途。

所有资源版权归 Shift Up 及相关权利方所有。请勿再分发提取出的美术与音频资源。
