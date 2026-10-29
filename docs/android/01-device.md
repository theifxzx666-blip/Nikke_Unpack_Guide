# 设备侧路径与拉取

包名以实际安装为准，下面用国际服作示例。根路径记作 `$P`：

```
$P = /storage/emulated/0/Android/data/<包名>
```

## 目录结构

```
$P/
├── cache/
│   └── StaticData.pack              静态数值表，加密 zip
├── files/
│   ├── com.shiftup.addressables/
│   │   ├── catalog.db               Addressables 主清单，SQLite，8,788,006 B
│   │   └── catalog.db.nds           96 B，签名块，不参与解密
│   └── com.shiftup.patch/
│       ├── core/
│       │   ├── catalog.ndb          桶清单（NKDB）
│       │   └── chunk/
│       │       ├── store.cdb        数据体，多个 pak 拼成
│       │       └── store.cdb.idx    块索引（CIDX）
│       ├── dp/  fd/  en/  ja/  ko/  同上结构
│       └── saus/
│           ├── catalog.ndb
│           └── raw/                 明文命名，Locale_*.lsc / perm_*.lsc / event_YYMMDD.lsc
```

## 三个容易找错的点

1. `StaticData.pack` 在 `cache/` 下，不在 `files/` 下。
2. `saus` 的文本走 `raw/` 明文目录，不经过 `store.cdb`，也不在 `files_chunktype` 里。该桶 `files_rawtype` 有 192 条，`files_chunktype` 只有 1 条。
3. `addressables/catalog.db` 和 `<桶>/catalog.ndb` 是两套完全不同的清单，格式也不同。前者是 SQLite 明文，后者是 NKDB 加密。别混。

## 拉取权限

`Android/data` 属主是 app，直接 `adb pull` 会 Permission denied。国产 ROM 封得更严，连 `adb shell` 也可能读不到。

稳妥做法是先提权拷到 `/sdcard/` 根目录，改权限，再 pull：

```bash
adb shell su -c "cp <源> /sdcard/_tmp && chmod 666 /sdcard/_tmp"
adb pull /sdcard/_tmp <本地>
```

`chmod 666` 必须做。`su -c` 出来的文件属主是 root，不改权限 pull 一定失败。

Windows 下 adb 参数里的正斜杠会被 MSYS 改写，Git Bash 里先 `export MSYS_NO_PATHCONV=1`。

## 需要 root 到什么程度

分三层看，不能一概而论：

| 层 | 路径 | 内容 | 需要 root |
| :--- | :--- | :--- | :--- |
| A | `/storage/emulated/0/Android/data/<包名>/` | `StaticData.pack`、`files/com.shiftup.*`，本方案全部素材都在这里 | 视 ROM 而定 |
| B | `/data/data/<包名>/` | shared_prefs、databases | 需要 |
| C | 进程内存 dump | 静态表 JSON | 需要 |

A 层理论上不属于 root 范畴，卡点在 Android 11 之后的 scoped storage。原生或类原生 ROM 一般 `adb shell cat` 能直读，`adb pull` 也能拉。国产 ROM 把 `Android/data` 对 adb shell 用户一起封了，只能靠一个持有 `MANAGE_EXTERNAL_STORAGE` 的进程先拷到 `/sdcard/` 根。

实测结论是国产 ROM 绕不过去，所以走了 `su`。真正和 root 无关的是解密环节，那些都在 PC 上做。

不 root 的两条替代路径，均未实测：

- 换 Android 10 及以下机型，那个版本还没有 scoped storage 封锁。
- 用带 root 的安卓模拟器，但官方包能否在模拟器里跑起来并下载完资源没试过。

全量几十 GB 素材，root 是最省事的一条。
