# NIKKE 客户端拆包方案

从安卓客户端提取美术、文本、音频资源的一套工程方案。覆盖设备路径、容器格式、定向取件、分类落盘全流程。

内容来自多次实际拆包，所有数字都是实测值。

## 解决什么问题

四个问题，按实际拆包的先后顺序排列：**先知道要什么，再只取那部分，再确认取到的东西可信，最后让产物能被别人接手。**
每个问题下面写清三件事：具体症状、用的机制、判定是否解决的标准。

### 1. 增量——这期到底新增了哪些文件

**症状**：catalog 里十几万条资源键，官方公告只说「新增活动」，不说新增哪些文件，人工翻图看不出改动。

**不能用键做差集**，两个方向都会错：

- 立绘这类一资源一个 bundle，键里带内容 hash（`…_c010_00_f17169d8….bundle`），重新打包后同一张图的键就变了 → 报成「新增」，假阳性
- 头像框、称号这类是**整表打成一个 bundle**（本期 `icons-user_frame(hd)` 258 个 Sprite、`icons-user_title` 90 个），键名不变、只换 hash → 报成「无变化」，假阴性

**做法**：差集单位取资源 ID，不取 bundle 键。每次版本落一份基线快照（全量键 + 各桶文件 hash + cache 清单 + uc catalog 键），下一版与基线做 ID 集合差，得新增 / 消失 / 变更三张表；对整表打包的族再下沉一层，做 Sprite 级与 `Locale_*` 文本层双向核对。

**判据**：新增列表能落到具体资源键；整表族能给出条目数。本期实测新增 6 个头像框、2 个称号，依据是 `uf_name_*` 239→245 与 `title_*_name` 75→77 两个方向互证，不是靠看图。

### 2. 取件——只要 200 MB 立绘，不拉 15 GB 整包

**症状**：资源被打成约 28 万个块散在五个桶里，单桶就是 GB 级（core 7.17 / dp 14.46 / fd 2.27 / ja 4.43 GB），一个 bundle 的块还可能横跨两个 pak。整包拉一遍要几十 GB 和数小时。

**做法**：四张表逐级收窄到块级，每级只用上一级的输出：

```
files_chunktype   资源键 → 文件 hash
      ↓
chunk_file_map    文件 → 块（按 file_offset 定序）
      ↓
chunks            块 → pak_id + pak 内偏移 + 压缩尺寸
      ↓
store.cdb.idx     hash → 数据体内位置 + 长度
```

拿到块级偏移后只切这几段：安卓侧 `dd` 分块导出再 `pull`（4096 对齐、断批重试），PC 侧按 idx 偏移直接读。取件体积 = 目标资源压缩块之和，与桶体积无关。

**判据**：解压后双向校验 —— `len(data) == original_size` **且** `file_offset == 已写入长度`，两道都过才算取到。zstd 对截断帧会「成功」返回部分数据，只判「解压没报错」会把残缺包当好包。

### 3. 归因——分清「它没有」和「我没取到」

**症状**：取件失败有三类成因 —— 键不存在、块未下发、偏移算错。混在一起就会反复重试拿不到的东西，或者把算错的偏移写成「资源缺失」进报告。

**做法**：先用全桶自证切掉「块未下发」这一类。`256 + Σ(idx.size)` 必须等于 `store.cdb` 实际字节数，闭合且区间无间隙 ⇒ idx 覆盖全部物理字节，查不到的块物理上不存在，不必再从 `pak_offset` 找绕路。catalog 条目数与 idx 条目数的差，就是「已登记未下发」，单独登记成缺口。

**判据**：五桶差 0、间隙 0；缺口能逐条归因到族与体积。本期 13,900 个缺口全部是低清版，可拆成 `spotmonster(sd)` 9,746 + `spotbackground(sd)` 5,631 + 少量 sd atlas，压缩后 0.49 GiB——而不是一句「低清没解出来」。

### 4. 交接——拆包不难，难的是每次都拆得一样

**症状**：同一套资源换个时间跑，目录层级、命名、去重规则都会变；产物只有图片没有来源，答不出「这张图对应哪个资源键、哪一版、哪个包」。于是每期都得重新问人，交付件没人敢接。

**做法**：固定三样东西 —— 目录骨架（A/B/C 三种模式，按读者要问的问题两段式切，不按采集管线切）、命名四条（目录去前导零、文件名留零、无官方名加 `_未定名_`、下游不带 `_tex`）、**一份改名与溯源映射**（采集目录 ↔ 入库目录 ↔ 资源键 ↔ 来源 pak / 块 hash）。技术中间产物统一收进 `_构建\` 或 `_源料\`，可整块删掉重跑。

**判据**：同一份输入重跑，产物路径与文件数完全一致；任意一个产物文件能反查回资源键与版本指纹（PC 端没有 `dumpsys`，改用文件指纹）。

## 链路

```
设备                     PC
──────────────────────────────────────────────────────
catalog.ndb  ──解 NKDB──>  SQLite 清单，资源键 → [块, 文件内偏移]
store.cdb.idx ──解 CIDX──>  hash → 数据体内位置
store.cdb    ──dd 切块──>  zstd 解压 → 按偏移拼接 → .bundle
                                                    ↓
                                              UnityPy 导出
                                                    ↓
                                            PNG / GLB / TSV / WAV
```

四个环节各自有坑，详见 [docs/android/](docs/android/)。

## 快速开始

先确认环境，再按需取件。完整命令见 [docs/android/03-fetch.md](docs/android/03-fetch.md)。

```bash
pip install -r tools/requirements.txt
adb devices                          # 设备要显示 device

# 拉七桶清单，每个几 MB
PKG=<包名>
P=/storage/emulated/0/Android/data/$PKG
adb shell su -c "cp $P/files/com.shiftup.patch/core/catalog.ndb /sdcard/_t && chmod 666 /sdcard/_t"
adb pull /sdcard/_t ./core_catalog.ndb
```

拿到 `catalog.ndb` 之后，按 [docs/android/02-containers.md](docs/android/02-containers.md) 解密成 SQLite，就能查任意资源键。

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [docs/01-overview.md](docs/01-overview.md) | 六阶段流程、三种工作模式、增量判定 |
| [docs/02-catalog.md](docs/02-catalog.md) | 43 类资源的键规律、桶、落盘目录、规格 |
| [docs/03-output.md](docs/03-output.md) | 目录骨架、命名规则、去重、跨服对齐 |
| [docs/04-tooling.md](docs/04-tooling.md) | 一键工具的接口设计，尚未实现 |
| [docs/android/](docs/android/) | 安卓链路：设备、容器、取件 |
| [docs/pc/](docs/pc/) | PC 端实测结论（2026-10-29 完成，43 类有产物 37、族名命中 38） |
| [AGENTS.md](AGENTS.md) | 给 AI 智能体的操作说明 |

## 环境

Python 3.11 以上，需要 UnityPy、zstandard、Pillow。adb 用 platform-tools。

设备的读取权限视 ROM 而定。国产 ROM 把 `Android/data` 对 adb shell 也封了，要用 `su` 中转；原生 ROM 通常能直接 pull。解密环节不需要 root，那是拿到字节之后在 PC 上做的。

版本与安装细节见 [tools/README.md](tools/README.md)。

## 已知限制

**PC 端已实测，结论在 [docs/pc/](docs/pc/)。** 容器格式与安卓同源，43 类有产物 37（族名命中 38）。
差异 10 处：`saus/raw` 磁盘名是 hash 而非明文、`.nab` 可直接出音频、无动态头像框族、
无莱彻躯干高模、无 `StaticData.pack` 等。

**低清版取不全 —— 已定论，不是没解出来。** 安卓侧 `chunks` 192,232 条、`idx` 只索引 178,332 条，
差的 13,900 个全是低清版 `(sd)`（压缩后 0.49 GiB）。PC 端实测 `256 + Σ(idx.size) == store.cdb` 字节数，
五桶全部闭合、零间隙，说明 `.idx` 100% 覆盖物理字节，查不到的块物理上就不存在，`pak_offset` 反推这条路是死的。
只能靠游戏内按需下载补。详见 [docs/pc/01-实测.md §6](docs/pc/01-实测.md)。

**语音格式已解。** `.nab` 是 bundle 后缀，内部就是标准 `AudioClip`，UnityPy 直接出 wav（48 kHz / 16 bit）。
语音三桶各 2,190 个加 saus 1 个、约 12 GB。安卓侧未实测，PC 侧已验。

**静态表要另想办法。** `StaticData.pack` 的双层 AES 在部分版本上无法用已知方式解开，替代路径是从进程内存 dump。

**没有现成工具。** 各环节都有可用脚本，但没有统一入口，需要按文档自己拼。

## 免责

仅用于个人研究、资料存档与资讯整理。不提供游戏本体，不提供可运行的修改版客户端，不用于商业用途。

所有资源版权归 Shift Up 及相关权利方所有。请勿再分发提取出的美术与音频资源。
