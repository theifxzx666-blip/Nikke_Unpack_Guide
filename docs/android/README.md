# 安卓客户端拆包

安卓端的资源不是一堆散文件，而是三层嵌套容器。要拿到一个具体资源，必须从清单一路串到数据体，中间少一层就定位不到。

```
① 地址清单      files/com.shiftup.addressables/catalog.db      人类可读地址 → bundle 内部名
② 桶清单        files/com.shiftup.patch/<桶>/catalog.ndb       资源键 → [块, 文件内偏移]
③ 块索引        files/com.shiftup.patch/<桶>/chunk/store.cdb.idx   块 hash → 数据体内位置
④ 数据体        files/com.shiftup.patch/<桶>/chunk/store.cdb      在此切成块再解压拼接
```

`①` 在实践中可以跳过。取件脚本直接用 `②` 里的 `key` 做通配匹配就够，因为 key 本身带完整路径。只有需要按 Addressables 地址反查时才用得上。

---

## 七桶分布

客户端把资源切成七个桶，体积和用途差别很大：

| 桶 | 文件键 | chunk | 原始 | 压缩后 | pak 数 | 内容 |
| :--- | --: | --: | --: | --: | --: | :--- |
| `core` | 27,905 | 192,232 | 14.98 GiB | 5.47 GiB | 6 | 模型 / 特效 / UI / 场景 |
| `dp` | 14,748 | 191,398 | 13.77 GiB | 10.45 GiB | 11 | 立绘 / 剧情图 / 音频 |
| `en` | 2,190 | 60,108 | 4.02 GiB | 4.01 GiB | 5 | 英语语音 |
| `ja` | 2,190 | 61,338 | 4.13 GiB | 4.13 GiB | 5 | 日语语音 |
| `ko` | 2,190 | 59,355 | 3.96 GiB | 3.96 GiB | 4 | 韩语语音 |
| `fd` | 517 | 43,307 | 3.65 GiB | 1.75 GiB | 2 | 地图 / 战场 |
| `saus` | 1 | 279 | 0.02 GiB | 0.02 GiB | 1 | 文本 + 静态表源包 |

合计原始约 44.5 GiB。

语音三桶压缩比 0.998，因为 `.nab` 内部已经是压缩音频，zstd 压不动。压缩后体积接近原始体积不等于判断错了格式，可能只是内容本来就有损压缩。

### 按分组查体积

知道要的东西在哪个桶、大概多大，能避免「以为只要 200 MB，结果拉了 5 GB」。

| 分组 | 桶 | 文件数 | 体积 | 内容 |
| :--- | :-: | --: | --: | :--- |
| `spotmonster(hd)` | core | 241 | 2,679.0 MB | BOSS 战场模型，高模 |
| `spotmonster(sd)` | core | 241 | 2,689.5 MB | 同上，低模 |
| `effect-spot-player_skill_library` | core | 2,337 | 1,984.9 MB | 我方技能特效 |
| `effect-spot-monster_skill_library` | core | 1,336 | 999.3 MB | 敌方技能特效 |
| `eventui-*` | core | 625 | 1,976.1 MB | 活动 UI |
| `spotskillcutscene` | core | 239 | 901.8 MB | 技能特写场景 |
| `livewallpaperprefabs` | core | 332 | 998.1 MB | 动态壁纸 |
| `audiogroup` | dp | 1,914 | 4,857.2 MB | 音效 / BGM |
| `scenariobackground(hd)` | dp | 1,709 | 2,576.9 MB | 剧情背景 |
| `spinestandingcharactergroup(hd)` | dp | 570 | 1,978.7 MB | 角色立绘 Spine |
| `spinecombatcharactergroup(hd)` | dp | 802 | 651.6 MB | 战斗小人 Spine |
| `sdcharacter-animations` | dp | 423 | 649.8 MB | SD 角色动画 |
| `icons-char-full(hd)` | dp | 549 | 259.2 MB | 角色立绘 |
| `eventfieldmapmodelgroup(hd)` | fd | 72 | 2,010.0 MB | 活动地图 |
| `campaignmapmodelgroup(hd)` | fd | 102 | 1,876.9 MB | 主线地图 |
| `lostsectormapmodelgroup(hd)` | fd | 51 | 316.1 MB | 迷失地带地图 |
| `ab` | en/ja/ko | 2,190 ×3 | 约 12.4 GB | 语音 `.nab` |

---

## 三篇分工

| 文件 | 回答什么 | 什么时候读 |
| :--- | :--- | :--- |
| [01-device.md](01-device.md) | 文件在设备哪个目录、怎么搬出来 | 第一次接设备 |
| [02-containers.md](02-containers.md) | 搬出来的字节是什么格式、怎么解 | 写解密或解析代码 |
| [03-fetch.md](03-fetch.md) | 怎么从一个资源键一路取到完整文件 | 写取件脚本 |

只想看某个资源在哪、叫什么名，读 [../02-catalog.md](../02-catalog.md)。
