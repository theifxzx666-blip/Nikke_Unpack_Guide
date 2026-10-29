# AGENTS.md

给 AI 智能体的操作说明。人读 [README.md](README.md)。

## 项目是什么

一套从 NIKKE 安卓客户端提取资源的工程方案：设备侧文件在哪、字节是什么格式、怎么定向取件、产物怎么落盘。

**是**：容器格式规格、取件算法、43 类资源的键规律、增量判定口径、落盘命名规范。

**不是**：游戏修改、私服搭建、内存注入、反汇编、美术二次创作。这些不在范围内，不要往这个方向扩展。

## 接手前必须知道的三条

**一、键集合差不等于新增。** 两版 catalog 的键直接 diff 会得到「新增 2,747 条」这种数字，绝大部分是同一资源 hash 变了的重打包条目。必须从键里正则提业务 ID 再做集合差，同一版本实际只新增 12 个 ID。用错方法会虚报两个数量级。

**二、导出成功不等于产物正确。** UnityPy 对一批包会导出不动的模型、内容错位的 bundle、缺件的动画，三种情况都不报错。必须打自检数字：模型看 `objects / triangles / vertices / ratio`，要求 `ratio ≥ 1.5`；动画看通道数大于 0；拼装看 `file_offset == 已写入长度`。看不到数字就当失败。

**三、索引不覆盖全量块。** `store.cdb.idx` 只索引 178,332 个块，而 `chunks` 表有 192,232 条，差的 13,900 个全是低清版 `(sd)`。取高清版不受影响，取低清版会遇到「chunk 不在 idx」。这个缺口还没解决，遇到时按未知处理。

## 文档地图

| 文件 | 读它的时机 |
| :--- | :--- |
| [docs/01-overview.md](docs/01-overview.md) | 要理解整体流程、三种工作模式、增量判定方法。**第一次接手先读这篇** |
| [docs/02-catalog.md](docs/02-catalog.md) | 要回答「某个资源在哪、叫什么名、什么规格」 |
| [docs/03-output.md](docs/03-output.md) | 要把产物按规范落盘 |
| [docs/04-tooling.md](docs/04-tooling.md) | 要写或改工具 |
| [docs/android/01-device.md](docs/android/01-device.md) | 第一次接设备，或拉取权限失败 |
| [docs/android/02-containers.md](docs/android/02-containers.md) | 要写解密或解析代码 |
| [docs/android/03-fetch.md](docs/android/03-fetch.md) | 要写取件脚本，或取件产物内容错乱 |
| [tools/README.md](tools/README.md) | 搭环境 |
| [docs/pc/README.md](docs/pc/README.md) | 有人问 PC 端。当前只有待办清单，没有方案 |

只回答具体问题的话，读一篇就够，不必通读。

## 工具与自检

```bash
adb version
python -c "import UnityPy, zstandard, PIL, sqlite3; print('ok')"
```

两行都通过才能动手。版本要求见 [tools/README.md](tools/README.md)。

执行环境是 Windows 时必做两件事：Python 子进程设 `PYTHONUTF8=1`，Git Bash 里调 adb 前 `export MSYS_NO_PATHCONV=1`。

## 产出约定

目录骨架和命名规则的权威定义在 [docs/03-output.md](docs/03-output.md)，不要另立一套。

硬底线：

- 目录名去前导零，文件名保留补零。这是母库既有写法，不要统一。
- 每件产物必须能倒推回原始资源键。改名了就把映射写进说明。
- 中文名只来自角色代号对照表。查不到标 `_未定名_`，不自行译名。
- 交付目录不留 `.bak`。
- 入库只新增不覆盖。

中间产物一律进 `_源料\` 或 `构建\`，不进正式目录。

## 改动约定

改这个仓库时：

- **实测数字不许动。** 行数、体积、尺寸、偏移、集合差数量都是从真实文件读出来的，概算或「大致」会毁掉整个方案的可信度。
- **新增结论要附证据。** 写「实测」就必须有对应的检查手段和结果。没有就写「未验证」。
- **保留易错点。** 每条易错点都对应一次真实返工，删掉等于让下一个人重踩。
- **不补充未验证的内容。** 尤其是 PC 端、`.nab` 音频格式、低清版取件这三块，目前都是未知。
- **不加入客户端内嵌常量。** `StaticData.pack` 的派生密钥材料不写进仓库。

新增条目的格式跟着所在文件走，不要引入新的标记体系。
