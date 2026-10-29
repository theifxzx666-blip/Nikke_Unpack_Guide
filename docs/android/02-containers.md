# 容器格式

设备上搬回来的字节一共三种容器，另有 `store.cdb` 的物理拼接规则需要单独说明。全部结构都是从二进制逐字节读出来的。

## 四级清单里两张表的结构

### 桶清单（`<桶>/catalog.ndb` 解密后的 SQLite）

以主桶 `core` 为例：

| 表 | 行数 | 字段 |
| :--- | --: | :--- |
| `files_chunktype` | 27,905 | `file_id, key, group_id` |
| `files_rawtype` | 2 | `file_id, key, hash, extension, size, group_id` |
| `chunks` | 192,232 | `chunk_id, hash, original_size, compressed_size, pak_id, pak_offset` |
| `chunk_file_map` | 298,179 | `chunk_id, file_id, file_offset` |
| `paks` | 6 | `pak_id, pak_name`，32 位 hex 命名 |
| `groups_chunktype` | 5 | `group_id, group_name` |

`key` 的形态是 `<分组>_assets_<分组>/<bundle 文件名>`：

```
spotmonster(hd)_assets_spotmonster/bbg003_2ef1....bundle
```

`chunk_file_map.file_offset` 是这个 chunk 在目标文件内部的写入偏移。拼装时必须按它排序并校验连续性，否则会静默产出一个内容错乱但体积正常的 bundle。

### 地址清单（`addressables/catalog.db`）

标准 Unity Addressables `ContentCatalogData`：

`keys`(101,985) / `key_entries`(253,760) / `entries`(62,728) / `internal_ids`(60,099) / `types`(130) / `provider_ids` / `resource_prov` / `entry_data`

作用是「人类可读的资源地址 → bundle 内部名」。取件脚本可以直接跳过这张表，用 `files_chunktype.key` 通配匹配就够，因为 key 自带完整路径。

---

## NKDB

`catalog.ndb`、`*.lsc`、`catalog.db` 都是这个格式。

| 偏移 | 长度 | 含义 |
| --: | --: | :--- |
| 0 | 4 | 魔数 `NKDB` |
| 4 | 4 | version，大端，实测 1 |
| 8 | 16 | AES-128 密钥，明文写在文件头 |
| 24 | 4 | segment_size，大端，实测 65,536 |
| 28 | 4 | segment_count，大端，实测 316 |
| 32 | N×L | 段偏移表，大端 |

`L` 不固定，按总长动态决定：

```python
length_byte_count = 5 if segment_size * segment_count > 0xFFFFFFFF else 4
```

偏移表是累积式的。读到第 i 个值就是第 i+1 段的结束位置，段长取差值。

每段解密：

```python
iv  = struct.pack('<ii', segment_index, segment_offset) + b'\x00' * 8
seg = AES.new(aes_key, AES.MODE_OFB, iv).decrypt(seg)
try:
    seg = zlib.decompress(seg)
except Exception:
    pass
```

### 没有全局密钥

密钥是生成文件时随机产生、明文写在偏移 8，每个文件都不一样。

实测三个文件三把不同的钥匙：

| 文件 | 密钥 |
| :--- | :--- |
| `addressables/catalog.db` | 16 字节，从偏移 8 读出 |
| `Locale_Monster` 的 `.lsc` | 与上面不同 |
| `Locale_Stage` 的 `.lsc` | 与前两个都不同 |

找一把万能密钥这条路不存在。正确做法是解每个文件时都读它自己的头。

验证：`catalog.db` 实测 8,788,006 B，解出 20,709,376 B 明文 SQLite，而 `316 × 65,536 = 20,709,376`，误差为零。

---

## CIDX

`store.cdb.idx`，块索引。

```
0    4B   魔数 "CIDX"
4    4B   未用，实测 01 00 00 00
8    4B   entry_count，小端
12   N×28B  条目，全部小端
```

每条 28 字节：

```
+0   16B  chunk hash
+16   8B  pos              在 store.cdb 里的绝对字节偏移
+24   4B  compressed_size
```

实测主桶 idx 4,993,324 B，声明 178,332 条，`12 + 28 × 178,332 = 4,993,308`，尾部多 16 字节，疑似 CRC，读取时忽略即可。

端序这一点必须记住：CIDX 小端，NKDB 大端。搞混会算出天文数字的偏移，然后 dd 出一个空文件，全程不报错。

---

## store.cdb 与多个 pak

`store.cdb` 是把多个 pak 按 id 顺序紧密重排后拼成的单文件。主桶 6 个 pak，实测三点吻合：

| pak | 块数 | Σcompressed_size | store.cdb 内起点 |
| --: | --: | --: | --: |
| 1 | 36,358 | 1,073,728,559 | 0（首块 pos = 256） |
| 2 | 34,115 | 1,073,729,306 | 1,073,728,815 |
| 3 | 42,637 | 1,073,739,813 | 2,147,458,121 |

推得：

```
pak_n 起点 = 256 + Σ_{i<n} Σ(compressed_size of pak_i)
```

256 字节是全局头，之后每个 pak 紧密相接，pak 之间没有 padding。

`chunks.pak_offset` 不是这个紧密偏移。它是原 pak 文件内的偏移，pak 内部存在空隙，`max(pak_offset + comp)` 比 `Σcomp` 大 25 万字节量级。所以不能用 `pak_offset` 直接去 `store.cdb` 里捞，必须走 idx。

### idx 是否覆盖全量物理字节 —— 一条可自证的校验

PC 端实测（[../pc/01-实测.md](../pc/01-实测.md)）给出了判断「缺块是索引漏了，还是字节本来就不在」的方法：

```python
tot = sum(size for _, size in idx.values())
assert 256 + tot == os.path.getsize('store.cdb')      # 五桶实测全部相等
# 再把 idx 的 (pos, size) 按 pos 排序，逐段检查 pos == 上一段结束位置，间隙数应为 0
```

两条都成立（差 0、间隙 0）⇒ **idx 100% 覆盖物理字节**，`idx` 查不到的 chunk 物理上就不存在。
这时 `pak_offset` 反推没有任何意义，缺块只能靠游戏内按需下载补。

若某桶这条校验不闭合，说明确实存在未索引区段，那才值得去试 `pak_offset` 换算。

顺带一个副产物：每个 pak 在 `store.cdb` 内的基址可以反推出来 ——

```python
base[pak] = mode(idx[hash].pos - chunks.pak_offset)   # 对同一 pak 的全部块取众数
```

PC 端实测 `base` 首尾严格相接（`base[n+1] = base[n] + Σcomp[n]`）**只在前几个 pak 成立**，
一旦中间有未下载的块，后面所有 pak 的 base 会整体前移，偏移量恰好等于缺块体积之和（三个 pak 实测差 0）。
⇒ **不要用累加 `Σcomp` 推 base，必须逐 pak 从 idx 反推。**

## 数据块

每块是单帧 zstd，解压目标长度等于 `chunks.original_size`。

实测主桶单块：最小 2 B，最大 1,048,576 B，平均 83,684 B。块上限就是 1 MiB。

---

## 两条例外链路

### saus/raw 不走 chunk

`saus` 的 `files_rawtype` 有 192 条，全部明文命名，直接躺在 `$P/files/com.shiftup.patch/saus/raw/`：

```
Locale_*.lsc               界面 / 表名本地化
perm_*.lsc                 权限 / 常驻文本
event_YYMMDD.lsc           每期上架的 BANNER 清单
lss/*SearchTable_<语>.lsc  搜索表
```

这批文件直接 pull，不用 dd、不用 zstd、不进 idx。拿到手只有一层 NKDB 要解。

实战价值很大。相邻两期 `event_*.lsc` 的 `sprite.name` 做集合差，就是本期新上的卡池和皮肤，分钟级操作，不需要全量基线。

### StaticData.pack 是唯一的双层 AES

位置在 `$P/cache/StaticData.pack`。

```
第 1 层，剥壳：
  k = PBKDF2(PRESHARED_64B, SALT2_32B, dkLen=32, count=10000, SHA256)
  d = AES-256-CBC(k[:16], iv=k[16:32]).decrypt(raw)  →  去 PKCS7
  d 是一个 zip，内含单个条目 "data"

第 2 层，解 data：
  k = PBKDF2(PRESHARED_64B, SALT1_32B, dkLen=32, count=10000, SHA256)
  ctr = int.from_bytes(k[16:32], 'big')
  对第 i 个 16B 块：keystream = AES-ECB.encrypt(k[:16], (ctr+i).to_bytes(16,'big'))
  明文 = 密文 XOR keystream  →  真 zip，约 9,606 个 .mpk
```

`PRESHARED` / `SALT1` / `SALT2` 三个常量是客户端内嵌物，本仓库不提供，需自行定位。

实测某些版本这套常量对官方安卓版无效，解出前两字节不是 `PK`，说明不同分发渠道可能用了不同常量。

已排除的排查方向，列出来免得重复劳动：SALT1/SALT2 互换、迭代 1k/10k/100k、用 GUID 字符串或 GUID 原始字节当 password、SHA256 四种直接拼接、跳过头部 16/24/32/64/128/256 字节再解。在 210 MB 的 `libil2cpp.so` 里搜 64 字节 PRESHARED 与两个 SALT 全部未命中，不是明文硬编码。

替代路径是从运行中的进程 dump 静态表，不解 pack，产出约 179 个 JSON。

`.mpk` 是 MemoryPack 二进制序列化，必须有 C# 类型定义才能反序列化。用 Python 硬解字段顺序会全错，需要 .NET 8 加对应类型定义。
