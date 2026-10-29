# 取件

一个资源键到完整文件，中间要走四步：查清单、查索引、切块、解压拼接。

## 算法

```
fetch(bucket, key):
  1. catalog 查 file_id → chunk_file_map 按 file_offset 排序 → [(hash, orig, comp)]
  2. idx 查每个 hash → pos
  3. 按 pos 排序，间隔 > 32 MiB 就断成新的一批（减少 dd 次数）
  4. 每批：起点向下对齐 4096，dd bs=4096 skip=起点/4096 count=块数
  5. pull 回来，按 (pos - 对齐起点) 切片
  6. zstd 解压，断言 len == original_size
  7. 断言 file_offset == 已写入长度，拼接
```

## 三道约束

违反任何一条都不会报错，只是悄悄产出错的东西。

### dd 必须 4096 对齐

`skip` 的单位是 4096 字节块，不是字节。

```python
clo_al = (clo // 4096) * 4096
skip   = clo_al // 4096
```

### 拼装必须验 file_offset 连续

只解压不验序，遇到 chunk 顺序错乱会产出长度正确、内容错位的 bundle。UnityPy 可能仍然打得开，错误延后到解析阶段才爆，那时候已经导了几百张图。

### chmod 666 必须先做

`su -c 'dd ... of=/sdcard/x'` 出来的文件属主是 root，不改权限 pull 必失败。

## 批量优化

按 `pos` 排序后，间隔超过 32 MiB 就断批。同一批用一次 `dd` 覆盖多个块，把「每块一次 adb 往返」压到「每批一次」。取 50 个 BOSS 模型时，有无这一层的差距是几十倍。

---

## 最小复现

只读环境，不解密任何东西，先把清单和索引拿到本地：

```bash
PKG=com.example.nikke
P=/storage/emulated/0/Android/data/$PKG

# 七桶清单，每个几 MB
for b in core dp fd en ja ko saus; do
  adb shell su -c "cp $P/files/com.shiftup.patch/$b/catalog.ndb /sdcard/_t && chmod 666 /sdcard/_t"
  adb pull /sdcard/_t ./${b}_catalog.ndb
done

# 块索引
adb shell su -c "cp $P/files/com.shiftup.patch/core/chunk/store.cdb.idx /sdcard/_t && chmod 666 /sdcard/_t"
adb pull /sdcard/_t ./core.cdb.idx

# 文本表，明文命名，直接 pull
adb shell su -c "cp -r $P/files/com.shiftup.patch/saus/raw /sdcard/_raw && chmod -R 666 /sdcard/_raw"
adb pull /sdcard/_raw ./saus_raw

# 解清单成 SQLite，之后交给 fetch(bucket, key)
python nkdb_dec.py core_catalog.ndb core_catalog.sqlite
```

Git Bash 下先 `export MSYS_NO_PATHCONV=1`，否则 adb 参数里的路径会被改写。

按 [02-containers.md](02-containers.md) 里的格式实现 `nkdb_dec.py` 与 `fetch()`，即可跑通全链路。`store.cdb` 单桶 5 到 10 GB，建议只在需要具体文件时才读，不要整桶拉。

---

## 已知缺口

下面五条都还没验证完，遇到时按未知处理，不要当已知条件往下推。

| # | 问题 | 现状 |
| :-: | :--- | :--- |
| 1 | idx 不覆盖全量块 | 主桶 `chunks` 192,232 条，idx 只索引 178,332 条，差 13,900 个。缺的**全部是低清版**：`spotmonster(sd)` 9,746 + `spotbackground(sd)` 5,631 + 少量 sd atlas，压缩后合计 0.49 GiB。高清版 100% 覆盖，取高清无影响，取低清会「chunk 不在 idx」 |
| 2 | 低清版怎么取，未解 | 只能用 `pak_offset`，但它与 `store.cdb` 的紧密偏移不等价，换算关系没实测出来。**PC 端已证伪这条路**，见下方 |
| 3 | `.pak` 是否真实存在设备上，未确认 | `paks` 表列了名字，但取件全走 `store.cdb`，没实际 `ls` 过 |
| 4 | `.nab` 格式未验 | 语音三桶各 2,190 个加 saus 1 个，共约 12 GB。**PC 端已解：`.nab` bundle 内是标准 `AudioClip`**，UnityPy 直接出 wav（48 kHz / 16 bit），不存在额外封装 |
| 5 | idx 尾部 16 字节 | 结构未知，疑似 CRC，不影响读取 |

缺 1 和 2 是同一个问题的两端，先解决 2 才能绕过 1。

### 关于 1 和 2：PC 端的定论

PC 端做了决定性验证（[../pc/01-实测.md](../pc/01-实测.md)）：

```
256 + Σ(idx.size)  ==  store.cdb 实际字节数     五桶全部相等，差 0
idx 的 (pos, size) 按 pos 排序后逐段相接            间隙 0
```

⇒ `.idx` 100% 覆盖 `store.cdb` 的物理字节，**没有未索引区段**。
凡是 `idx` 里查不到的 chunk，物理上就不在文件里，`pak_offset` 反推捞不到东西 —— 这条路不是「没解出来」，是「本来就没有字节」。

**安卓侧建议先跑同一条 Σ 校验**：

```python
tot = sum(sz for _, sz in idx.items())
print(256 + tot, os.path.getsize('store.cdb'))     # 相等则 1/2 可一并关闭
```

若闭合，则 13,900 个 sd 块同样是物理缺失，只能靠游戏内触发按需下载补；若不闭合，才值得继续找换算关系。
