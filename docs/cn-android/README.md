# 国服安卓（ADB）

容器与国服 PC 相同（Addressables 清单 + Unity Cache），差别只在路径与搬运方式：**单文件 pull，不需要 dd 切块**。

## 实测基数

| 项 | 值 |
| :--- | :--- |
| 包名 / 版本 | `com.tencent.nikke` / `22.1.1`（code 2201001，`lastUpdateTime` 2026-10-01 08:48:58） |
| 资源根 `$D` | `/sdcard/Android/data/com.tencent.nikke/files` |
| 清单 | `$D/com.unity.addressables/` **177 组**（354 个文件，`.json` + `.hash`） |
| 缓存 | `$D/UnityCache/Shared/<hashA>/<hashB>/__data`，**22,003 个** `<hashA>` 目录 |
| 文本表 | `$D/saus/saus/lss/*.lss` |
| 其它 | `NK/Dolphin/`、`assembly/Android/`、`Share/`（截图，与资源无关） |

## 链路

```bash
export MSYS_NO_PATHCONV=1
D=/sdcard/Android/data/com.tencent.nikke/files

# ① 清单：177 组，按需取，别全拉
adb pull "$D/com.unity.addressables/1420424509.json" build/cn/adb_catalog.json

# ② 文本表：明文 SQLite，拉来可直接查
adb pull "$D/saus/saus/lss/Locale_System.lss" build/cn/Locale_System.lss

# ③ 资源包：整包 pull（不需要 dd）
adb pull "$D/UnityCache/Shared/<hashA>/<hashB>/__data" out.bundle
```

## 与国服 PC 的差异

| 项 | PC（WeGame） | 安卓 22.1.1 |
| :--- | :--- | :--- |
| 清单组数 | 189 | 177 |
| 主清单路径 | `LocalLow/com_tencent/.../com.unity.addressables` | `$D/com.unity.addressables` |
| 文本表路径 | `<安装目录>/nikke_Data/runtime_data/saus/saus/lss` | `$D/saus/saus/lss` |
| 文本表内容 | `Locale_System.lss` 4,362,240 B / 10,670 行 | **同一文件、同一大小、同一行数** |
| 缓存头部 | 抽样 22,210 个全为 `UnityFS` | 抽样 3 个全为 `UnityFS` |
| 取件 | 本地直读 | `adb pull` |

两条结论：

1. **文本层两平台发布同一份**，可互校，也可只在一侧采集。
2. **缓存都是明文**，NKAB 不在缓存里；遇到 `NKAB` 才需要 NAU。

## 与安卓国际服的差异

| 项 | 国际服 | 国服 |
| :--- | :--- | :--- |
| 取件粒度 | 块级，必须 dd + 拼装校验 | 整文件 pull |
| 清单 | `catalog.ndb`（NKDB 加密） | Addressables 明文 JSON |
| 索引 | `store.cdb.idx`（CIDX） | 无，靠包内对象名反查 |
| 版本三要素 | `dumpsys package` | `dumpsys package` |

**取件粒度是这里最省事的一点**：国服安卓不需要处理 `iflag`、不需要 4096 对齐、不需要验 `file_offset` 连续性——但要自己解决「文件在哪个 hashB 目录下」。

## 定位

和国服 PC 同一套办法：`__data` 目录名不可推导，只能读包内对象名反查。

设备上没有索引怎么办：把目标包的 `<hashA>/<hashB>` 抽样 pull 回来（单包几十 KB 到几 MB），在 PC 侧用 `nk.py export` 看对象名，确认后再定型；或者先 pull 全量缓存再本地建索引（8 GB 级，不要随手做）。

## 已验证的样本

| 类 | 来源 | 结果 |
| :--- | :--- | :--- |
| 生文本表 | `Locale_System.lss` | 4,362,240 B / 10,670 行 |
| 资源包 | `UnityCache/Shared/0003b393.../99c03eaa.../__data` | 177,501 B → Texture2D 2（128² / 512²） |

完整的四场景样本表见 [../samples.md](../samples.md)。
