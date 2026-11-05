---
name: nikke-unpack
description: 从胜利女神（NIKKE）客户端拆包取素材，覆盖四个场景——国际服/国服 × PC/安卓。国际服走 NKDB 清单 + store.cdb 分块（安卓用 adb dd 定点读），国服走 Addressables 明文清单 + UnityCache 目录树（NKAB 密文才需 NAU）。涉及「拆包」「解包」「取素材」「Addressables」「NKDB」「store.cdb」「NKAB」「NAU」「adb 取件」「客户端资源在哪」时使用。
agent_created: true
---

# NIKKE 客户端拆包

四个场景不是四套方案，是 **2×2**：**容器形态**决定清单与数据体格式（硬分叉），**端**只决定字节怎么搬。

容器形态**与服名不一一对应**：国际服都是七桶；国服既有七桶（官网/客户端版）也有缓存（WeGame 版与安卓）。

## 第一步：先判容器，再判端

顺序不能反。判错的代价不对称——把缓存形态当七桶，会去 `store.cdb` 找不存在的文件，卡死在第一步。

| 判据 | 七桶形态 | 缓存形态 |
| :--- | :--- | :--- |
| 目录特征 | 有 `com.shiftup.patch/{core,dp,fd,en,ja,ko,saus}` | 有 `runtime_data/cache` 或 `UnityCache/Shared` |
| 清单 | `<桶>/catalog.ndb`，魔数 `NKDB` | `com.unity.addressables/*.json`，明文 |
| 数据体 | `<桶>/chunk/store.cdb` + `.idx`（`CIDX`） | `cache/<32hexA>/<32hexB>/__data` |
| 文本表 | `saus/raw/<16B hash hex>.lsc`，**NKDB 加密** | `saus/saus/lss/*.lss`，**明文 SQLite** |
| 版本 | 安卓 `dumpsys package`；PC 只能文件指纹 | 同左 |

场景名的 `intl` / `cn` 指 **容器族**，不是服名：国服装七桶客户端时按 `intl-*` 跑。

一行自查：`python tools/nk.py doctor --scene <intl-pc|intl-adb|cn-pc|cn-adb> --root <根>`

## 铁律

1. **先读 4 字节再决定要不要解密**。`UnityFS` 直读，`NKAB` 才过 NAU。不要预设「国服就是加密的」——本机实测国服 PC 22,210 个缓存条目全是明文。
2. **只切需要的段，不整桶拉**。国际服 `store.cdb` 单桶 5~14 GB；安卓上尤其不能整桶 pull。
3. **三道断言一个都不能省**：`len(data)==original_size`、`file_offset==已写入长度`、chunk 不在 idx 立即抛。zstd 对截断帧会「成功」返回部分数据，不校验就静默出错。
4. **取键必须过滤 `(hd)`**。同名 HD/SD 并存，SD 后写覆盖 HD，症状是「所有键 0 命中」。
5. **看不到自检数字就当失败**。贴图看对象数与尺寸，模型看 `ratio ≥ 1.5`，文本看行数。UnityPy 对一批包会导出不动的模型、错位的 bundle、缺件的动画，三种都不报错。
6. **不猜路径、不猜键名、不猜译名**。查不到就写「未验证」，别写「应该」。
7. **扫全量包必须进程隔离**。实测有单个 39 KB 的包会让 UnityPy **段错误**（0xC0000005），
   `try/except` 抓不住，`Pool` 里一个 worker 崩了主进程就永远等下去——症状是「不报错、只是不动了」。
   用 `cnindex` 的分片 subprocess 模式，崩了只丢一个包并记账跳过。
8. **批量才谈效率，单件谈不了**。单件 2.6 s 里 2.05 s 是解释器 + `import UnityPy` + CIDX 解析，
   改代码优化不掉；用 `batch` 一个进程吃整份键表，20 件快 16 倍、100 件快 52 倍。
9. **先确认资源在哪个服，再动手**。两服版本不同步，同一个活动可能只在一边有
   （MARIA-n：国际服 198 个包，国服 9 条音频）。`locate` 一条命令 0.4 秒给出两服的命中数与类型构成，
   不看这个数字就开跑，等于赌运气。

## 快速开始

```bash
# 环境（Windows 必须，否则中文与路径双崩）
export MSYS_NO_PATHCONV=1
PYTHONUTF8=1

# 第 0 步 —— 先问「这个资源哪个服有、有多少」
python tools/nk.py locate "marian" --intl-root "D:/.../NIKKEG" --cn-root "E:/.../nikke_Data"
#   输出两服命中数 + 类型构成 + 一句话结论；只给一侧路径时另一侧明确报「未检查」

# 国际服 PC —— 单件：取件+导出一条命令
python tools/nk.py scan --scene intl-pc --root "D:/.../NIKKEG"
python tools/nk.py find --scene intl-pc --root "D:/.../NIKKEG" --bucket dp "c010_00"
python tools/nk.py pull --scene intl-pc --root "D:/.../NIKKEG" --bucket dp "<完整键>" -o x/

# 国际服 PC —— 按活动名一次搜全七桶，直接出键表（检索百毫秒级）
python tools/nk.py find "marian" --all --cat "<已解密 catalog 目录>" --keys keys.txt
#   多桶会拆成 keys_core.txt / keys_dp.txt / …，因为 batch 一次只吃一个桶
python tools/nk.py batch --scene intl-pc --root "D:/.../NIKKEG" --bucket core keys_core.txt -o out/core --jobs 4

# 国际服 PC —— 批量：一个进程吃整份键表，别写 shell 循环
python tools/nk.py batch --scene intl-pc --root "D:/.../NIKKEG" --bucket dp keys.txt -o out/
#   默认先预检 idx：清单有、本地没下载的键会在开跑前报出来
python tools/nk.py batch keys.txt --bucket dp -o out/ --skip-missing   # 只拉能拉的

# 国际服安卓（清单与索引拉到本地，数据体按块 dd）
python tools/nk.py pull --scene intl-adb --root "/sdcard/Android/data/com.proximabeta.nikke/files/com.shiftup.patch" --bucket dp "<键>" -o x/

# 国服（两端同法，先建索引再取）
python tools/nk.py cnindex --root "<cache 根>" -o build/cn_index.sqlite --jobs 4
python tools/nk.py cnget   --root "<cache 根>" "<32hex 或对象名>" -o x.bundle
```

**批量是唯一有效的提速手段**。单件 2.6 s 里有 2.05 s 是解释器、`import UnityPy`（1.75 s）与
CIDX 解析（152 ms）的固定成本，逐件起进程等于每件都重付一遍。实测：20 件从 52.4 s 压到
3.2 s（16 倍），100 件从约 4.4 分钟压到 5.0 s（约 52 倍）。`--jobs` 默认 4，八进程只再快 8%。
详见 [docs/05-效率实测.md](docs/05-效率实测.md)。

依赖：UnityPy 1.25.x + zstandard + Pillow + pycryptodome；国服 NKAB 另需 NAU（.NET 8）。

## 四场景要点

### 国际服 PC

- **资源根不在安装目录**。在 `<安装目录>/Unity/com_proximabeta_NIKKE/com.shiftup.patch`；`game` 下只有 exe。最省事的定位法是读 `%LOCALAPPDATA%Low\com_proximabeta\NIKKE\Player.log` 里的 `trace GetGameResourcePath`。
- 七桶一次解密只要 2 秒，之后任意键可查。
- `.idx` 100% 覆盖物理字节（`256 + Σ(idx.size) == store.cdb`，五桶闭合）⇒ 查不到的块物理不存在，`pak_offset` 反推是死路。
- 互动型/装配型场景（`spotbackground`）要还原装配再渲染，不能直接导一张图。

### 国际服安卓（ADB）

- 三条硬约束：**必须 `exec-out`**（`adb shell` 会把 dd 统计行混进 stdout）、**必须 `iflag=skip_bytes,count_bytes`**（toybox 默认按记录数）、**拼装按 `file_offset`**（不是物理偏移）。
- 清单与 `.idx` 各几 MB，先 pull 到本地解一次，再决定切哪几块。
- 按 `pos` 排序，间隔 > 32 MiB 断批，一批一次 dd，把「每块一次往返」压成「每批一次」。
- `Android/data` 权限：本机 Mi 10 Pro 可直读；国产 ROM 需 `su -c "cp … /sdcard/_t && chmod 666"`，`chmod` 不能省。

### 国服 PC / 安卓（缓存形态）

- **清单 → 缓存没有直连**。缓存目录名是随机 hash，与 bundle 名无确定关系；md5 / sha1 的各种变体实测全部不命中。**不要试图算路径**。
- 唯一可用的桥：清单 `m_InternalIds` 里 bundle 名的末尾 **32 hex**，等于包内 `<hash>.bundle` 对象名。建「对象名 → 路径」索引来反查。
- 索引是一次性成本，本机实测：22,210 包 / 8.46 GB → 132,516 个不同对象名，库 335 MB。
  真正干活约 4 分钟；吞吐会从 84 包/秒衰减到 24 包/秒，**ETA 要按滚动窗口算，别用全程均值**。
- **毒包必须隔离**：`49a8af4f…`（39 KB）单独跑就 SIGSEGV。见铁律 7，用 `cnindex` 的分片 subprocess 模式。
- 续跑去重键必须规范化（`abspath → normpath → normcase`）。`E:/x` 与 `E:\x` 是同一文件不同字符串，
  按原样比对会让续跑静默全废、每次全量重跑。
- 文本表 `.lss` 是**明文 SQLite**，直接 `sqlite3` 打开，不需要任何解密。
- 取件粒度是整文件，没有 dd、没有 4096 对齐、没有 `file_offset` 校验——难点全在「定位」。
- NAU 会停在 `Press enter`，子进程必须给空 stdin，否则永久挂起。
- 若装的是**七桶形态的国服客户端**，走上面「国际服 PC/安卓」那一节，容器完全一致。

## 版本指纹（判断「版本真的变了」）

PC 取不到 `versionName`/`versionCode`，用文件指纹：各桶 `catalog.ndb` 大小 + mtime + 键数，`store.cdb` 大小，`cache` 目录数与总字节。

魔数校验表：

| 文件 | 头 4 字节 | 判定 |
| :--- | :--- | :--- |
| `<桶>/catalog.ndb` | `4e4b4442` | `NKDB` |
| `<桶>/chunk/store.cdb` | `43424c42` | `CBLB` |
| `<桶>/chunk/store.cdb.idx` | `43494458` | `CIDX` |
| `cache/*/__data` | `556e6974` / `4e4b4142` | `UnityFS` 直读 / `NKAB` 过 NAU |
| `*.lss`（国服） | `53514c69` | `SQLi`，明文 |

## 增量判定（版更场景）

- 用 **ID 集合差**，不用键集合差。键里带内容 hash，重打包后键变，直接 diff 会虚报两个数量级。
- 正则必须允许连字符：`^[a-z-]+\(`，否则 `icons-char-si(hd)` 会被并进 `icons-char`。
- 基线必须同服同源，跨服混用会虚报新增。
- 新增与消失都要能解释。判不出来源的 ID 标 `_未定名_c<ID>_<皮肤>`，不臆造译名。

## 文档地图

| 要做什么 | 读哪篇 |
| :--- | :--- |
| **从线索到成品的完整流程** | **[docs/07-采集工作流.md](docs/07-采集工作流.md)** |
| 不确定该走哪个场景 | [docs/00-场景矩阵.md](docs/00-场景矩阵.md) |
| 要看四场景实测样本与数字 | [docs/samples.md](docs/samples.md) |
| 国际服 PC | [docs/intl-pc/](docs/intl-pc/README.md) → [01-实测](docs/intl-pc/01-实测.md) / [02-场景装配](docs/intl-pc/02-场景装配.md) |
| 国际服安卓 | [docs/intl-android/README.md](docs/intl-android/README.md) |
| 国服 PC | [docs/cn-pc/README.md](docs/cn-pc/README.md) → [01-实测](docs/cn-pc/01-实测.md) |
| 国服安卓 | [docs/cn-android/README.md](docs/cn-android/README.md) |
| 容器字节结构 | [docs/common/容器-国际服.md](docs/common/容器-国际服.md) |
| 取件算法 | [docs/common/取件-国际服.md](docs/common/取件-国际服.md) |
| 43 类资源键规律 | [docs/common/02-catalog.md](docs/common/02-catalog.md) |
| 落盘命名 | [docs/common/03-output.md](docs/common/03-output.md) |

## 边界

只做**读取**：不改客户端、不注入、不读进程内存、不绕过登录、不动存档。所有资源版权属 Shift Up 及相关权利方，仅用于个人研究，不再分发。
