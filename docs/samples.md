# 最小采集样本

每个场景按「导出路径」各取 1~2 个：贴图 / 图集 / Spine 三件套 / 文本 / 音频。目的是证明链路通，不是攒素材——**样本不入库，只记数字**。

验收口径：每个样本必须同时给出「取到多少字节」和「解出什么」。少了任一半，都不算通过。

## 国际服 PC

版本：七桶 `core` 清单 27,378,514 B / 27,905 键。取件全部本地按 `.idx` 偏移直读。

| # | 类 | 键 | 块数 | 字节 | MD5 前 8 | 导出 |
| :-: | :--- | :--- | --: | --: | :--- | :--- |
| 1 | 立绘（画布 + 紧裁） | `icons-char-full(hd)_assets_c010_00_f17169d8….bundle` | 7 | 1,061,760 | `a1f8ef2d` | Texture2D 1 + Sprite 1，**1024×1024** |
| 2 | Spine 待机 | `spinestandingcharactergroup(hd)_assets_spine/standing/c010/00_hd_51b81b57….bundle` | 48 | 5,155,968 | `d06fa1e0` | Texture2D 1（2048²）+ TextAsset 2（`.skel` + `.atlas`） |
| 3 | SD 小人 | `sdcharacters_assets_c010_00_var_0313864c….bundle` | 9 | 594,864 | `45bb9059` | Texture2D 3 + Mesh 3，256² / 512² |
| 4 | 头像框图集 | `icons-user_frame(hd)_assets_all_9d211bce….bundle` | 201 | 18,378,896 | `c64d4745` | Texture2D 258 + Sprite 258，256² / 512² |
| 5 | 语音 | `ja` 桶 `ab/000771aa….nab` | 37 | 2,731,712 | `37f9ad37` | AudioClip 93 → 93 个 wav / 27 MB |
| 6 | 生文本表 | `saus/raw/<hash>`，key `Locale_System.lsc` | — | 2,916,158 | — | NKDB → 6,746,112 B SQLite，`Locale_System` **10,950 行** |

第 2 条要注意：Spine 的 `.skel` / `.atlas` 在 UnityPy 里是 `TextAsset`，不是独立容器，别去找第三方解析器。
第 5 条要注意：一个 `.nab` 里装 93 个 `AudioClip`，按包计数会严重低估语音量。

## 国际服安卓

版本 153.6.10。设备侧 `core/store.cdb` 5,339,989,493 B，`ranges/` 为空。

| # | 类 | 键 | 块数 | 字节 | 耗时 | 导出 |
| :-: | :--- | :--- | --: | --: | --: | :--- |
| 1 | 立绘（画布 + 紧裁） | `icons-char-full(hd)_assets_c010_00_435214c0….bundle` | 4 | 481,040 | 6.2 s | Texture2D 1 + Sprite 1，1024×1024 |
| 2 | 生文本表 | `saus/raw/1cc05a5bf29eb2a922b429df52e27a3d.lsc` | — | 2,916,158 | — | NKDB → 6,746,112 B，**10,950 行** |

两条跨平台结论：

- 同一族立绘 PC 是 1,061,760 B / 7 块，安卓是 481,040 B / 4 块，**解出同为 1024²** —— 块数与体积不能用来判断资源是否一致，必须看导出物。
- 文本表两侧磁盘 hash 完全相同（`1cc05a5b…`）、字节完全相同、行数完全相同 ⇒ **文本层两平台发布同一份**。

## 国服 PC（WeGame 版）

清单 189 组，缓存 22,210 个 `__data` / 8.46 GB，全部明文 `UnityFS`。

| # | 类 | 来源 | 字节 | 导出 |
| :-: | :--- | :--- | --: | :--- |
| 1 | 资源包（头像/半身像图集） | `cache/0003b393…/24bf2237…/__data` | 183,118 | Texture2D 2，**128×128 / 512×512** |
| 2 | 生文本表 | `runtime_data/saus/saus/lss/Locale_System.lss` | 4,362,240 | 明文 SQLite，`Locale_System` **10,670 行** |

文本表**不需要解密**，直接 `sqlite3` 打开。

## 国服安卓

版本 22.1.1。清单 177 组，缓存 `UnityCache/Shared`，22,003 个 `<hashA>` 目录。

| # | 类 | 来源 | 字节 | 导出 |
| :-: | :--- | :--- | --: | :--- |
| 1 | 资源包（头像/半身像图集） | `UnityCache/Shared/0003b393…/99c03eaa…/__data` | 177,501 | Texture2D 2，**128×128 / 512×512** |
| 2 | 生文本表 | `saus/saus/lss/Locale_System.lss` | 4,362,240 | 明文 SQLite，**10,670 行** |

`hashA` 两平台相同（`0003b393…`，由下载 URL 决定），`hashB` 不同（`24bf2237…` vs `99c03eaa…`，由内容决定）。**跨平台不能靠比对 hashB 判断资源是否同一**。

## 跨场景对照

| 维度 | 国际服 PC | 国际服安卓 | 国服 PC | 国服安卓 |
| :--- | :--- | :--- | :--- | :--- |
| 样本字节（同类图集包） | 18,378,896（258 张） | — | 183,118（2 张） | 177,501（2 张） |
| 文本表行数 | 10,950 | 10,950 | 10,670 | 10,670 |
| 文本表加密 | NKDB | NKDB | 无 | 无 |
| 解出贴图上限 | 2048² | 2048² | 512²（本样本） | 512²（本样本） |

国服图集包只有 2 张，是因为抽到的缓存条目本身只有 2 张，**不代表国服没有 258 张的整族包**——那是抽样问题，不是能力问题。写结论时不要越界。

## 复现

```bash
# 国际服 PC
python tools/nk.py scan   --scene intl-pc --root "<安装目录>"
python tools/nk.py get    --scene intl-pc --root "<安装目录>" --bucket dp "<键>" -o x.bundle
python tools/nk.py export x.bundle -o x/

# 国际服安卓
export MSYS_NO_PATHCONV=1
python tools/nk.py get    --scene intl-adb --root "/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch" --bucket dp "<键>" -o x.bundle

# 国服（两端同法）
python tools/nk.py cnindex --root "<cache 根>" --jobs 10
python tools/nk.py cnget   --root "<cache 根>" "<32hex 或对象名>" -o x.bundle
python tools/nk.py export  x.bundle -o x/
```
