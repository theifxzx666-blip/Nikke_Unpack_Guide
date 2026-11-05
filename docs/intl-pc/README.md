# 国际服 PC

容器是自研 `NKDB` + `store.cdb`，七桶平铺；文件就在本地，取件只需按索引 `seek`。

## 一眼定位

| 项 | 值 |
| :--- | :--- |
| 安装目录 | `.../NIKKEG`（启动器目录，含 `Launcher/ NIKKE/ Unity/`） |
| **资源根** | `<安装目录>/Unity/com_proximabeta_NIKKE/com.shiftup.patch` |
| 七桶 | `core dp fd en ja ko saus` |
| 体量 | `store.cdb` 合计 28.3 GB |

**资源根不在安装目录的 `game` 下**，那里只有 exe 与 `nikke_Data`。定位最稳的一条是读启动器日志：

```
%LOCALAPPDATA%Low\com_proximabeta\NIKKE\Player.log
  → 搜 trace GetGameResourcePath  →  后面就是绝对路径
```

日志同目录还有 `bg-downloader\`（时间是 UTC，+8 才是本地）。

## 取件

七个桶的 `catalog.ndb` 一次解开（2 秒），之后任意键都能定位：

```bash
python tools/nk.py scan --scene intl-pc --root "<安装目录>"
python tools/nk.py find --scene intl-pc --root "<安装目录>" --bucket dp "c010_00"
python tools/nk.py get  --scene intl-pc --root "<安装目录>" --bucket dp "<完整键>" -o out.bundle
python tools/nk.py export out.bundle -o out/
```

`get` 里的三道断言必须留着：`len(data)==original_size`、`file_offset==已写入长度`、chunk 不在 idx 立刻抛。

## 与安卓的差异

同一份容器格式，10 处具体差异见 [01-实测.md](01-实测.md)。影响动手的三条：

| # | 项 | 结论 |
| :-: | :--- | :--- |
| 1 | `saus/raw` 磁盘名 | 16 B hash 的 hex（`1cc05a5b....lsc`），映射在 `files_rawtype.hash`，**不是明文命名** |
| 2 | 静态表 | **路径不存在**。`core/raw/*.db` 是 Addressables 目录库（8 张表），不是 179 张业务表 |
| 3 | 动态头像框 | `icons-dynamic` **全站零命中**，PC 无该族 |

## 已知边界

- 低清 `(sd)` 缺块：`.idx` 100% 覆盖物理字节，缺的块物理上不在文件里，只能靠游戏内按需下载补。
- 莱彻整具模型：`spotmonster(hd)` 只装骨骼占位与特效件，不是完整高模。
- 43 类有产物 37 类；不可交付的 6 类原因逐条列在 [01-实测.md](01-实测.md) §8。

## 场景装配

`spotbackground` 装配型场景不在本页范围内，单独一篇：[02-场景装配.md](02-场景装配.md)（软光栅出 2560×1440 全景）。
