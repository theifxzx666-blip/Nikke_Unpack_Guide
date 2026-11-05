# AGENTS.md

给 AI 智能体的操作说明。人读 [README.md](README.md)，技能入口是 [SKILL.md](SKILL.md)。

## 项目是什么

一套从 NIKKE 客户端读取资源的工程方案，覆盖四个场景：**国际服 / 国服 × PC / 安卓**。

**是**：容器格式规格、清单与索引结构、取件算法、43 类资源的键规律、四场景差异、增量判定口径、落盘命名。

**不是**：游戏修改、私服搭建、内存注入、反汇编、绕过登录、美术二次创作。不要往这些方向扩展。

## 接手前必须知道的三条

**一、先判容器，再判端。** 容器形态决定清单与数据体（硬分叉），端只决定字节怎么搬。七桶形态是 `catalog.ndb`(NKDB) + `store.cdb`(CIDX)；缓存形态是 Addressables 明文 JSON + `cache/<hexA>/<hexB>/__data`。**容器与服名不一一对应**——国服既有七桶客户端也有 WeGame 缓存版，看目录结构，不看服名。判错的代价不对称：往错的方向找，会卡在第一步且毫无提示。

**二、键集合差不等于新增。** 两版 catalog 的键直接 diff 会得到「新增 2,747 条」这种数字，绝大部分是同一资源 hash 变了的重打包条目。必须从键里正则提业务 ID 再做集合差，同一版本实际只新增 12 个 ID。用错方法会虚报两个数量级。

**三、导出成功不等于产物正确。** UnityPy 对一批包会导出不动的模型、内容错位的 bundle、缺件的动画，三种都不报错。必须打自检数字：模型看 `objects / triangles / vertices / ratio`，要求 `ratio ≥ 1.5`；动画看通道数 > 0；拼装看 `file_offset == 已写入长度`。**看不到数字就当失败。**

## 路由表

先读 [docs/00-场景矩阵.md](docs/00-场景矩阵.md)，再按判据落到对应目录。

| 判据 | 结论 | 读这篇 |
| :--- | :--- | :--- |
| 有 `com.shiftup.patch/` 七桶，`catalog.ndb` 头是 `NKDB` | 七桶形态 | [docs/intl-pc/](docs/intl-pc/README.md) 或 [docs/intl-android/](docs/intl-android/README.md) |
| 有 `nikke_Data/runtime_data/cache` 或 `UnityCache/Shared` | 缓存形态 | [docs/cn-pc/](docs/cn-pc/README.md) 或 [docs/cn-android/](docs/cn-android/README.md) |
| 都不像 | 停手核对安装目录 | 本文件「接手前必须知道的三条」第一条 |

端侧判断很简单：资源在本地磁盘 → PC；要 `adb` → 安卓。服名只影响内容（键数、语种、资源是否下发），不影响算法。

## 工具

单一入口 `tools/nk.py`，子命令与 [docs/common/04-tooling.md](docs/common/04-tooling.md) 的契约对齐（当前实现了 `doctor` / `scan` / `find` / `get` / `cnindex` / `cnget` / `export`）。

```bash
python -c "import UnityPy, zstandard, PIL, Crypto; print('ok')"   # 依赖自查
```

执行环境是 Windows 时必做两件事：Python 子进程设 `PYTHONUTF8=1`，Git Bash 里调 adb 前 `export MSYS_NO_PATHCONV=1`。

路径含 `[` `]` `(` 时（如 `[3]Nikke`）通配符会误判，一律加引号；PowerShell 用 `-LiteralPath`。

## 硬底线

- **只读客户端**，不写入、不改 ACL、不动存档。
- **只切需要的段**。`store.cdb` 单桶 5~14 GB，绝不整桶拉。
- **不猜路径、不猜键名、不猜译名**。查不到就写「未验证」。
- **不把「待验」当「已知」**往下推。矩阵表里标待验的格子，实测前不要引用。
- **不在仓库里放二进制**：`.bundle` / `.cdb` / `.ndb` / `.pack` / `.lsc` / `.lss` / `.mpk` 都不入库。
- 不写客户端内嵌常量（`StaticData.pack` 的派生密钥材料）。

## 改动约定

改这个仓库时：

- **实测数字不许动。** 行数、体积、尺寸、偏移、集合差数量都是从真实文件读出来的，概算会毁掉整个方案的可信度。
- **新增结论要附证据。** 写「实测」就必须有检查手段和结果，没有就写「未验证」。
- **保留易错点。** 每条都对应一次真实返工，删掉等于让下一个人重踩。
- **标注版本与实例。** 同一个服可能有多个分发版本（例如国服 WeGame 版与官网版，缓存一个明文一个 NKAB），数字必须带版本与路径，不能混写。
- 新增条目的格式跟着所在文件走，不要引入新的标记体系。

## 已知的「文档与现实不符」记录

| 旧说法 | 实测 | 处置 |
| :--- | :--- | :--- |
| 安卓 `saus/raw` 明文命名 | 153.6.10 实为 16 B hash hex，与国际服 PC 一致 | 已在 [docs/intl-android/](docs/intl-android/README.md) 更正 |
| 国服缓存是 NKAB 密文 | WeGame 版 22,210 个 `__data` 全为明文 `UnityFS` | 改为「先读 4 字节再判」，见 [SKILL.md](SKILL.md) 铁律 1 |
| `store.cdb` 零间隙紧密排列 | 国际服五桶闭合，国服四桶有 71.8 MiB 空隙 | 已在 [docs/cn-pc/01-实测.md](docs/cn-pc/01-实测.md) §4 标注适用范围 |

遇到新的不一致，追加到这张表，不要只改正文。
