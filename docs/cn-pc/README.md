# 国服 PC（WeGame 版）

和另外三个场景的容器完全不是一套东西：**没有 `store.cdb`，没有 `catalog.ndb`**，用的是 Unity Addressables 明文清单 + Unity Cache 目录树。

## 一眼定位

| 项 | 值 |
| :--- | :--- |
| 安装目录 | `E:/WeGameApps/rail_apps/胜利女神：新的希望(2002017)` |
| 资源根 | `<安装目录>/nikke_Data/runtime_data` |
| 缓存 | `runtime_data/cache/<32hexA>/<32hexB>/__data` |
| 清单 | `%LocalAppData%Low/com_tencent/胜利女神：新的希望/com.unity.addressables/` |
| 文本表 | `runtime_data/saus/saus/lss/*.lss` |

注意路径里带全角冒号与括号，`ls "E:/...[3]..."` 这类写法在 Git Bash 里会被当通配符，一律加引号。

## 实测基数

| 项 | 值 |
| :--- | :--- |
| `<hashA>` 目录 | 21,927 |
| `__data` 文件 | 22,210 |
| 缓存总字节 | 8.46 GB |
| 清单组数 | 189 组（`.json` + `.hash`） |
| 主清单 `assets/aa/catalog.json` | 42,796,213 B |
| 文本表 | 69 个 `.lss`；`Locale_System.lss` 4,362,240 B / 10,670 行 |

## 清单长什么样

```json
{"m_LocatorId":"AddressablesMainContentCatalog", ...,
 "m_InternalIds":[
   "{NK.Addressable.HostConst.HostCoreLoadURL}/icons-char-full(hd)_assets_c010_00_<32hex>.bundle", ...],
 "m_KeyDataString":"...", "m_BucketDataString":"...", "m_EntryDataString":"..."}
```

`m_InternalIds` 有 49,024 条，**末尾 32 hex 就是包内 `<hash>.bundle` 对象名**，这是清单与缓存之间唯一可用的桥。

## 定位：清单 → 缓存，没有直连

缓存目录名是随机 hash，与 bundle 名无确定关系。实测 md5 的多种变体全部不命中：

| 试过的输入 | 结果 |
| :--- | :--- |
| 完整 bundle 名 / 去后缀 / 小写 | 不命中 |
| `{HostConst...}/` 前缀拼完整名 | 不命中 |
| 名字里的 32 hex 后缀本身 | 不命中 |
| md5 与 sha1 双算法 | 不命中 |

⇒ **不要试图算路径**。只能按内容反查：读每个 `__data` 的对象名，建 `对象名 → 路径` 索引，再拿清单里的 32 hex 去对。

```bash
python tools/nk.py cnindex --root "<安装目录>/nikke_Data/runtime_data/cache" --jobs 10
python tools/nk.py cnget   --root "<安装目录>/nikke_Data/runtime_data/cache" "<32hex>" -o out.bundle
```

索引默认落 `build/cn_index.sqlite`（已在 `.gitignore` 里，别提交）。是一次性成本：22,210 个包、8.46 GB，10 进程实测 10 分钟以上（大包拖尾）。建一次可反复查。

## NKAB 不一定在缓存里

本机实测：22,210 个 `__data` **全部是明文 `UnityFS`**（前 4 字节 `Unit`），APK 内 38 个 `assets/abs/` 包也全是 `UnityFS` 或 manifest。

⇒ **先读 4 字节，再决定要不要解密**：

```python
head = open(p, 'rb').read(4)
# b'Unit' → UnityFS，直接 UnityPy
# b'NKAB' → 需 NAU（NikkeAssetUnpacker）
```

NAU 只在处理**下载流密文**时需要。另一个国服实例（详见 [01-实测.md](01-实测.md)）的缓存确实是 NKAB v14，同名资源必须过 NAU 才能解——所以这条判据不能预设，只能当场测。

NAU 调用有个坑：它会停在 `Press enter`，必须给空 stdin，否则子进程永久挂起。

## 文本表是明文

`runtime_data/saus/saus/lss/*.lss` 是**标准 SQLite**，不经 NKDB：

```python
con = sqlite3.connect('file:Locale_System.lss?mode=ro', uri=True)
con.execute('select count(*) from Locale_System')   # 10,670
```

对比：国际服同一个表是 `.lsc`，NKDB 加密，解出 10,950 行。**同名不同格式**，别套错解压器。

## 已实测的取件

| 类 | 来源 | 结果 |
| :--- | :--- | :--- |
| 生文本表 | `Locale_System.lss` | 4,362,240 B → 10,670 行 |
| 资源包 | `cache/<hashA>/<hashB>/__data` | 见 [../samples.md](../samples.md) 的国服 PC 行 |

资源包的命中率与族名结论见 [01-实测.md](01-实测.md)；那份是对**另一个国服实例**的实测（客户端现已不在本机，包体数字不可与本页混用）。
