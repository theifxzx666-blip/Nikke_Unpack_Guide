# 国际服安卓（ADB）

容器与 PC 同构，多出来的是「字节怎么从设备搬到 PC」。核心不是拉全量，是**只切需要的那几段**。

## 实测基数

| 项 | 值 |
| :--- | :--- |
| 设备 / 系统 | Mi 10 Pro（`2fb37497`），`adb` 状态必须是 `device` |
| 包名 / 版本 | `com.proximabeta.nikke` / `153.6.10`（code 1530610） |
| 资源根 `$P` | `/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch` |
| core 清单 | 18,204,098 B |
| core `store.cdb` | 5,339,989,493 B，`.idx` 4,993,352 B |
| 下载收尾判据 | `core/chunk/ranges/` 为空（实测 0 个文件） |

## 链路

```bash
export MSYS_NO_PATHCONV=1        # 不设这个，adb 参数里的 /storage/... 会被 MSYS 改写
P=/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch

# ① 只拉清单与索引（各几 MB），数据体一个字节都不拉
adb pull $P/core/catalog.ndb        build/dev/core.ndb
adb pull $P/core/chunk/store.cdb.idx build/dev/core.idx

# ② 解密 + 查表 + 按块 dd（工具已封装）
python tools/nk.py find --scene intl-adb --root "$P" --bucket dp "icons-char-full(hd)_assets_c010"
python tools/nk.py get  --scene intl-adb --root "$P" --bucket dp "<完整键>" -o out.bundle
```

取一个 4 块的立绘包，端到端 6.2 秒（4 次 adb 往返）。

## 三条硬约束

违反任何一条都**不会报错**，只会悄悄产出错的东西。

1. **必须 `exec-out`**，不能 `adb shell`。`adb shell` 会把 dd 的统计行混进 stdout（实测多 171 B）。
2. **必须 `iflag=skip_bytes,count_bytes`**。toybox dd 的 `skip`/`count` 默认按记录数算，不是字节。
3. **拼装按 `file_offset`**，不是按物理偏移排序。按物理偏移排会得到「长度对、包头错」的包。

## 权限

`Android/data` 属主是 app，直接 `adb pull` 会 `Permission denied`。实测这台 Mi 10 Pro 不需要 `su`，`adb pull` 直读成功；国产 ROM 封得更严时走 `su` 中转：

```bash
adb shell su -c "cp <源> /sdcard/_t && chmod 666 /sdcard/_t"
adb pull /sdcard/_t <本地>
```

`chmod 666` 不能省：`su -c` 出来的文件属主是 root。

## 与 PC 的实测差异

| 项 | PC | 安卓 153.6.10 |
| :--- | :--- | :--- |
| core 清单 | 27,378,514 B | 18,204,098 B |
| core `store.cdb` | 7,172,646,468 B | 5,339,989,493 B |
| `saus/raw` 磁盘命名 | 16 B hash hex | **同样是 hash hex**（旧文档写的「明文命名」已不成立） |
| 同名资源字节 | `icons-char-full(hd)_assets_c010_00_*` 1,061,760 B | 481,040 B（4 块），解出同为 1024² |

文本表两侧同一个文件：`Locale_System` 磁盘 hash 都是 `1cc05a5b...`，2,916,158 B，解出 6,746,112 B / 10,950 行 —— 说明**文本层两平台发布同一份**，可以直接互校。

## 已知缺口

`chunks` 表条目多于 `.idx` 索引条目，缺的**全部是低清 `(sd)`**。高清 100% 覆盖，取高清不受影响；取低清会撞「chunk 不在 idx」，此时按物理缺失处理，不要试 `pak_offset` 反推。
