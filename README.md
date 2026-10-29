# NIKKE 客户端拆包方案

从安卓客户端提取美术、文本、音频资源的一套工程方案。覆盖设备路径、容器格式、定向取件、分类落盘全流程。

内容来自多次实际拆包，所有数字都是实测值。

## 解决什么问题

**只知道「这期更新了什么」，不知道具体有哪些文件。** 用两版清单做 ID 集合差，得到精确的新增列表，不用全量扫描。

**只要 200 MB 的立绘，不想拉 15 GB 的包。** 四级清单串联到块级，按需切块，只取用到的那部分。

**提取出来的东西散在各处，没人能接手。** 固定的目录骨架加命名规则，加一份能倒推回资源键的映射。

拆包本身不难，难的是每次都拆得一样、别人能接着用。

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

**低清版取不全 —— 已定论，不是没解出来。** `256 + Σ(idx.size) == store.cdb` 字节数，五桶全部闭合、零间隙，
说明 `.idx` 100% 覆盖物理字节，查不到的块物理上就不存在，`pak_offset` 反推这条路是死的。
只能靠游戏内按需下载补。详见 [docs/pc/01-实测.md §6](docs/pc/01-实测.md)。

**语音格式已解。** `.nab` 是 bundle 后缀，内部就是标准 `AudioClip`，UnityPy 直接出 wav（48 kHz / 16 bit）。
安卓侧未实测，PC 侧已验。

**静态表要另想办法。** `StaticData.pack` 的双层 AES 在部分版本上无法用已知方式解开，替代路径是从进程内存 dump。

**没有现成工具。** 各环节都有可用脚本，但没有统一入口，需要按文档自己拼。

## 免责

仅用于个人研究、资料存档与资讯整理。不提供游戏本体，不提供可运行的修改版客户端，不用于商业用途。

所有资源版权归 Shift Up 及相关权利方所有。请勿再分发提取出的美术与音频资源。
