# NIKKE 客户端拆包方案

从客户端提资源的一套工程方案，覆盖五层：清单 → 定位 → 取件 → 导出 → 落盘。
文中数字均为实测值，出处标在对应文档。

**核心是拆包这一条主链**；每期版更的增量提取，是在主链上加两步的扩展场景，不是另一套方案。

## 概述

读法：先看框架确认有哪几层，再按层往下走。只取某个资源，走完 ①~⑤；要做版更增量，再加基线快照与 ID 差集。

| 顺序 | 看什么 | 要解决的事 | 去哪看 |
| :-: | :--- | :--- | :--- |
| 1 | 框架 | 一共几层、主链与场景是什么关系 | 本文下一节 |
| 2 | 容器 | 三个文件头：`catalog.ndb` / `store.cdb` / `.idx` | [02-containers](docs/android/02-containers.md) |
| 3 | 清单 | 资源键怎么一路串到块级偏移 | [03-fetch](docs/android/03-fetch.md) |
| 4 | 取件 | 只切需要的那几段，怎么校验 | [03-fetch](docs/android/03-fetch.md) |
| 5 | 落盘 | 目录骨架、命名四条、溯源映射 | [03-output](docs/03-output.md) |
| 6 | 版更 | 主链上补哪两步 | 本文「版更增量提取」 |

## 框架

五层，每层只依赖上一层：

```
资源键  c010_00 · icn_..._frame · Locale_Skill
   │
   ├─ ① 清单   catalog.ndb → SQLite（七表）                     设备侧
   ├─ ② 定位   store.cdb.idx（CIDX）→ 数据体内偏移与长度         设备侧
   ├─ ③ 取件   store.cdb（CBLB）→ 切块 → zstd → 按偏移拼接       设备 → PC
   ├─ ④ 导出   UnityFS → UnityPy → PNG / GLB / WAV / TSV         PC
   └─ ⑤ 落盘   骨架 + 命名四条 + 溯源映射                         PC
```

| 层 | 关键对象 | 文档 |
| :-: | :--- | :--- |
| ① | 七表：`paks` / `groups_chunktype` / `groups_rawtype` / `files_chunktype` / `chunks` / `chunk_file_map` / `files_rawtype` | [02-containers](docs/android/02-containers.md) |
| ② | `store.cdb.idx`：`CIDX` + 28 B/条（小端，与 NKDB 的大端相反） | 同上 |
| ③ | `store.cdb`：`CBLB` + 256 B 头 + 裸 zstd 帧紧密拼接 | [03-fetch](docs/android/03-fetch.md) |
| ④ | 43 类资源的键规律、桶、导出形态 | [02-catalog](docs/02-catalog.md) |
| ⑤ | A/B/C 三种目录形态、命名四条、改名映射 | [03-output](docs/03-output.md) |

安卓与 PC 同源，差异见 [docs/pc/](docs/pc/)。

## 拆包（主链）

阶段 0–6，每阶段一个判据，不过就停。

| 阶段 | 做什么 | 判据 |
| :-: | :--- | :--- |
| 0 环境自检 | 设备、包名、版本三要素、下载是否收尾、七桶 revision、工具链 | `ranges` 与 `raw` 为空；`adb devices` 为 `device` 而非 `unauthorized` |
| 1 基线对齐 | 取上一版全量键快照 | 新旧 `catalog.ndb` 大小与键数可比 |
| 2 增量判定 | ID 集合差 | 新增与消失都能解释 |
| 3 定向取件 | 四表串到块级，只切需要的段 | `len == original_size` 且 `file_offset` 连续 |
| 4 导出校验 | UnityPy / glTF / 文本解析 | 贴图对象数与张数一致、模型 `ratio ≥ 1.5`、文本不可归组为 0 |
| 5 分类落盘 | 骨架 + 命名 + 映射 | 任一产物可反查资源键 |
| 6 总结入库 | 说明文档、联系表、入库登记、索引三件套 | 登记含 MD5；索引三件套齐（总清单 md / 资源库清单 xlsx / 代号对照表 xlsx） |

细节与踩坑见 [docs/01-overview.md](docs/01-overview.md)，设备侧见 [docs/android/01-device.md](docs/android/01-device.md)。

## 版更增量提取（扩展场景）

主链不动，只加两步、补一处深挖。对应 [模式 B](docs/01-overview.md)。

| 环节 | 主链 | 版更场景 |
| :--- | :--- | :--- |
| 基线 | 无 | 每版落快照：全量键 + 各桶文件 hash + cache 清单 + uc catalog 键 |
| 定位资源 | 按需求给正则 | 与基线做 ID 集合差 → 新增 / 消失 / 变更三张表 |
| 整表族 | 按族取即可 | 再下沉一层：Sprite 级 + `Locale_*` 文本层双向核 |

差集单位是资源 ID，不是 bundle 键，两个方向的错都要避开：

- 一资源一 bundle，键里带内容 hash（`…_c010_00_f17169d8….bundle`），重打包后键变 → 假阳性
- 整表打包（`icons-user_frame(hd)` 258 Sprite、`icons_user_title` 90 Sprite），键不变只换 hash → 假阴性

本期实测：`uf_name_*` 239→245、`title_*_name` 75→77，对应 6 个头像框、2 个称号。
判定规则与反例见 [docs/01-overview.md](docs/01-overview.md)。

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
| [docs/01-overview.md](docs/01-overview.md) | 阶段 0~6、三种工作模式、增量判定与反例 |
| [docs/02-catalog.md](docs/02-catalog.md) | 43 类资源的键规律、桶、落盘目录、规格 |
| [docs/03-output.md](docs/03-output.md) | 目录骨架、命名规则、去重、跨服对齐 |
| [docs/04-tooling.md](docs/04-tooling.md) | 一键工具的接口设计，尚未实现 |
| [docs/android/](docs/android/) | 安卓链路：设备、容器、取件 |
| [docs/pc/](docs/pc/) | PC 端实测结论（43 类有产物 37、族名命中 38） |
| [AGENTS.md](AGENTS.md) | 给 AI 智能体的操作说明 |

## 环境

Python 3.11 以上，UnityPy / zstandard / Pillow，adb 用 platform-tools。
国产 ROM 把 `Android/data` 对 adb shell 也封了，需 `su` 中转；原生 ROM 可直接 pull。解密在 PC 侧做，不需要 root。
安装细节见 [tools/README.md](tools/README.md)。

## 已知限制

| 项 | 结论 | 详见 |
| :--- | :--- | :--- |
| PC 端 | 容器同源；43 类有产物 37（族名命中 38），差异 10 处：`saus/raw` 磁盘名是 hash、`.nab` 直出音频、无动态头像框族、无莱彻躯干高模、无 `StaticData.pack` | [docs/pc/](docs/pc/) |
| 低清版 | 安卓 `chunks` 192,232 / `idx` 178,332，差 13,900 全为 `(sd)`，0.49 GiB。PC 实测 `256 + Σ(idx.size)` 五桶闭合、零间隙 ⇒ 查不到的块物理上不存在，`pak_offset` 反推是死路，只能靠游戏内按需下载补 | [01-实测 §6](docs/pc/01-实测.md) |
| 语音 | `.nab` 是 bundle 后缀，内部即标准 `AudioClip`，UnityPy 直出 wav（48 kHz / 16 bit）。三桶各 2,190 + saus 1，约 12 GB | [01-实测 §5](docs/pc/01-实测.md) |
| 静态表 | `StaticData.pack` 双层 AES 在部分版本上解不开，替代路径是从进程内存 dump | [03-fetch](docs/android/03-fetch.md) |
| 工具 | 各环节有可用脚本，无统一入口，需按文档自己拼 | [04-tooling](docs/04-tooling.md) |

## 免责

仅用于个人研究、资料存档与资讯整理。不提供游戏本体，不提供可运行的修改版客户端，不用于商业用途。

所有资源版权归 Shift Up 及相关权利方所有。请勿再分发提取出的美术与音频资源。
