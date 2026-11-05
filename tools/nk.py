# -*- coding: utf-8 -*-
"""NIKKE 拆包统一入口 —— 四场景：国际服/国服 × PC/安卓。

只用标准库 + zstandard + UnityPy + Pillow。国服的 NKAB 解密交给外部 NAU.exe。

    python nk.py doctor  --scene intl-pc --root <客户端根>
    python nk.py scan    --scene intl-pc --root <客户端根> --out build/
    python nk.py find    --scene intl-pc --root <客户端根> "c010_00"
    python nk.py get     --scene intl-pc --root <客户端根> "<完整键>" -o out.bundle
    python nk.py cnindex --root <cache 根> -o build/cn_index.sqlite
    python nk.py cnget   --root <cache 根> "c010_00" -o out.bundle
    python nk.py export  out.bundle -o out/

场景取值：intl-pc / intl-adb / cn-pc / cn-adb
"""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import zlib

import zstandard as zstd


# ---------------------------------------------------------------- 依赖自检

def _alt_python():
    """找一个装齐依赖的解释器，只为了把「换个解释器」变成可复制的命令。"""
    cand = os.environ.get('NK_PYTHON')
    if cand and os.path.exists(cand):
        return cand
    for p in ('F:/Codex/Supports/venv_assetparse/Scripts/python.exe',
              'F:/Codex/依赖/venv-build/Scripts/python.exe'):
        if not os.path.exists(p):
            continue
        try:
            r = subprocess.run([p, '-c', 'import UnityPy, zstandard, PIL'],
                               capture_output=True, timeout=30)
        except Exception:
            continue
        if r.returncode == 0:
            return p
    return ''


def require(*mods):
    """缺依赖时一次说清，别让 89 件各自 ModuleNotFoundError 一遍。

    Windows 上这个坑很常见：`python` 指向的解释器没装 UnityPy，装齐的在别的 venv 里。
    逐件报错只会刷满一屏且看不出解法，所以直接给一条能复制粘贴的完整命令。
    """
    missing = []
    for m in mods:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if not missing:
        return
    lines = ['缺少依赖: %s' % ', '.join(missing),
             '当前解释器: %s' % sys.executable]
    alt = _alt_python()
    if alt:
        argv = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
        lines += ['已装齐的解释器，直接换这条跑:',
                  '  "%s" %s' % (alt, ' '.join(argv))]
    else:
        lines.append('装法: pip install -r tools/requirements.txt')
    print('\n'.join(lines), file=sys.stderr)
    sys.exit(4)


# ---------------------------------------------------------------- 国际服：清单

def nkdb_decrypt(src, dst):
    """NKDB -> 明文 SQLite。密钥明文写在偏移 8，每文件不同，没有全局密钥。"""
    data = open(src, 'rb').read()
    if data[:4] != b'NKDB':
        raise ValueError('不是 NKDB: %s' % src)
    aes_key = data[8:24]
    seg_size = int.from_bytes(data[24:28], 'big')
    seg_cnt = int.from_bytes(data[28:32], 'big')
    lbc = 5 if seg_size * seg_cnt > 0xFFFFFFFF else 4
    pos, cur, segs = 32, None, []
    cur = int.from_bytes(data[pos:pos + lbc], 'big')
    pos += lbc
    for i in range(seg_cnt):
        nxt = int.from_bytes(data[pos:pos + lbc], 'big')
        pos += lbc
        segs.append((cur, nxt - cur, i))
        cur = nxt
    from Crypto.Cipher import AES
    out = bytearray()
    for off, ln, idx in segs:
        iv = struct.pack('<ii', idx, off) + b'\x00' * 8
        seg = AES.new(aes_key, AES.MODE_OFB, iv=iv).decrypt(data[off:off + ln])
        try:
            seg = zlib.decompress(seg)
        except Exception:
            pass
        out += seg
    open(dst, 'wb').write(bytes(out))
    return {'segments': len(segs), 'bytes': len(out), 'key': aes_key.hex()}


_CIDX_CACHE = {}


def load_cidx(path):
    """CIDX -> {hash16: (pos, compressed_size)}。小端，与 NKDB 的大端相反。

    按 (路径, mtime, 大小) 缓存：单个 idx 6~7 MB，批量取件时逐件重读纯属浪费。
    客户端更新会改 mtime，缓存自然失效。
    """
    try:
        st = os.stat(path)
        ck = (os.path.abspath(path), st.st_mtime, st.st_size)
    except OSError:
        ck = None
    if ck and ck in _CIDX_CACHE:
        return _CIDX_CACHE[ck]
    raw = open(path, 'rb').read()
    magic, _ver, cnt = struct.unpack_from('<4sII', raw, 0)
    if magic != b'CIDX':
        raise ValueError('不是 CIDX: %s' % path)
    idx = {}
    for k in range(cnt):
        o = 12 + k * 28
        if o + 28 > len(raw):
            break
        idx[raw[o:o + 16]] = struct.unpack_from('<QI', raw, o + 16)
    if ck:
        _CIDX_CACHE[ck] = idx
    return idx


INTL_BUCKETS = ('core', 'dp', 'fd', 'en', 'ja', 'ko', 'saus')


def _ensure_cat(root, bucket, adb=False, catdir=''):
    """取某桶 catalog.sqlite 的本地路径，没有就就地解密一次。

    `catdir` 指向已经解密好的目录时直接复用，省掉重复解密
    （七个桶全解一遍是分钟级，检索本身只要百毫秒级）。
    """
    if catdir:
        for name in ('%s_catalog.sqlite' % bucket, '%s.sqlite' % bucket):
            p = os.path.join(catdir, name)
            if os.path.exists(p):
                return p
        raise FileNotFoundError('%s 里没有 %s 的 catalog' % (catdir, bucket))
    if adb:
        cache = os.path.join('build', '_cat_adb')
        cat = os.path.join(cache, '%s.sqlite' % bucket)
        if not os.path.exists(cat):
            os.makedirs(cache, exist_ok=True)
            tmp = os.path.join(cache, '%s_catalog.ndb' % bucket)
            _adb_pull('%s/%s/catalog.ndb' % (root.rstrip('/'), bucket), tmp)
            nkdb_decrypt(tmp, cat)
        return cat
    patch = intl_root(root)
    cat = os.path.join('build', '_cat', '%s.sqlite' % bucket)
    if not os.path.exists(cat):
        nkdb_decrypt(os.path.join(patch, bucket, 'catalog.ndb'), cat)
    return cat


def find_keys(root, needle, buckets, adb=False, catdir=''):
    """按子串检索完整键，返回 ({桶: [键…]}, [(桶, 跳过原因)…])。

    为什么要跨桶：同一个活动名会散落在 core（UI/音频/Spine）、dp（剧情背景）、
    fd/en/ja/ko/saus（文本）里，只查默认的 core 会漏掉一大半，而且漏得没有提示。
    """
    import sqlite3
    hit, miss = {}, []
    pat = '%' + needle.lower() + '%'
    for b in buckets:
        try:
            cat = _ensure_cat(root, b, adb=adb, catdir=catdir)
        except Exception as e:
            miss.append((b, '%s: %s' % (type(e).__name__, e)))
            continue
        if not os.path.exists(cat):
            miss.append((b, 'catalog 不存在'))
            continue
        con = sqlite3.connect('file:%s?mode=ro' % cat.replace(os.sep, '/'), uri=True)
        try:
            rows = [r[0] for r in con.execute(
                'SELECT key FROM files_chunktype WHERE lower(key) LIKE ? ORDER BY key', (pat,))]
        finally:
            con.close()
        if rows:
            hit[b] = rows
    return hit, miss


def write_keys(hit, path):
    """把检索结果落成 batch 能直接吃的键表，返回 {桶: 文件路径}。

    batch 一次只认一个桶，所以多桶必须分文件，不能拼成一份——
    混桶的键表会让另一桶的键全部报 KeyError。
    """
    base, ext = os.path.splitext(path)
    ext = ext or '.txt'
    written = {}
    for b, keys in hit.items():
        p = path if len(hit) == 1 else '%s_%s%s' % (base, b, ext)
        d = os.path.dirname(os.path.abspath(p))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(keys) + '\n')
        written[b] = p
    return written


CN_ID_CACHE = os.path.join('build', '_cat_cn')


def cn_catalog_json(root):
    """国服根 -> Addressables 清单。给 cache 根、nikke_Data、安装目录都能认。"""
    cands = [os.path.join(root, 'StreamingAssets', 'aa', 'catalog.json'),
             os.path.join(root, 'nikke_Data', 'StreamingAssets', 'aa', 'catalog.json')]
    p = os.path.abspath(root)
    for _ in range(5):
        cands.append(os.path.join(p, 'StreamingAssets', 'aa', 'catalog.json'))
        p = os.path.dirname(p)
    for c in cands:
        if os.path.exists(c):
            return c
    raise FileNotFoundError('找不到国服 catalog.json（StreamingAssets/aa/catalog.json）: %s' % root)


def cn_ids(root):
    """把清单里的明文路径摊成一行一条，作为检索底表。

    41 MB JSON 每次解析约 1 秒，摊平后 8 MB 文本，子串匹配几十毫秒。
    缓存名带 size+mtime，游戏更新后自动重建，不用手动清。
    """
    cat = cn_catalog_json(root)
    st = os.stat(cat)
    os.makedirs(CN_ID_CACHE, exist_ok=True)
    dst = os.path.join(CN_ID_CACHE, 'ids_%d_%d.txt' % (st.st_size, int(st.st_mtime)))
    if not os.path.exists(dst):
        with open(cat, encoding='utf-8') as f:
            ids = json.load(f).get('m_InternalIds') or []
        tmp = dst + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(ids) + '\n')
        os.replace(tmp, dst)
    return dst, cat


def cn_objname(path):
    """bundle 路径 -> 包内对象名，也就是国服缓存索引里的 name。

        ...\\eventui-marian_assets_story_event_list_marian_part2_9fac3295.bundle
          -> story_event_list_marian_part2
    取不到 _assets_ 就退回去掉末 32 hex 的文件名。
    """
    name = os.path.basename(path.strip())
    if name.endswith('.bundle'):
        name = name[:-7]
    m = re.search(r'_([0-9a-fA-F]{32})$', name)
    if m:
        name = name[:m.start()]
    i = name.rfind('_assets_')
    if i >= 0:
        name = name[i + 8:]
    return name


def _kinds(items, sep=''):
    """按命名前缀粗分类型，给「这一侧到底有什么」一个直观画像。"""
    import collections
    c = collections.Counter()
    for x in items:
        if sep:
            i = x.find(sep)
            head = x[:i] if i > 0 else x
        else:
            head = x.split('_')[0]
        c[head.replace('(sd)', '').replace('(hd)', '')] += 1
    return dict(c.most_common(5))


def _verdict(servers):
    """把两服的命中数压成一句「去哪拿」。"""
    it = servers.get('intl') or {}
    cn = servers.get('cn') or {}
    ie, ce = it.get('error'), cn.get('error')
    if ie and ce:
        return {'go': 'unknown', 'why': '两服都检查失败：%s / %s' % (ie, ce)}
    if ie:
        return {'go': 'cn' if cn.get('total') else 'unknown',
                'why': '国际服检查失败（%s），只能按国服结果判断' % ie}
    if ce:
        return {'go': 'intl' if it.get('total') else 'unknown',
                'why': '国服检查失败（%s），只能按国际服结果判断' % ce}
    i, c = it.get('total', 0), cn.get('total', 0)
    ci, cc = it.get('checked'), cn.get('checked')
    if ci and cc:
        if not i and not c:
            return {'go': 'none',
                    'why': '两个服都没命中：关键词可能拼错，或客户端版本还没上这个资源'}
        if i and not c:
            return {'go': 'intl', 'why': '国服清单里没有，去国际服'}
        if c and not i:
            return {'go': 'cn', 'why': '国际服目录里没有，去国服'}
        hi, lo = max(i, c), min(i, c)
        why = '两服都有：国际服 %d 条 / 国服 %d 条，按语种和画质选' % (i, c)
        if lo * 10 < hi:
            why += '；%s只有 %d 条，量级差一个数量级以上，先看 samples 确认是不是同一类资源' % (
                '国服' if c < i else '国际服', lo)
        return {'go': 'both', 'why': why}
    if ci:
        return {'go': 'intl' if i else 'none',
                'why': '只检查了国际服，命中 %d 条；国服未提供路径' % i}
    if cc:
        return {'go': 'cn' if c else 'none',
                'why': '只检查了国服，命中 %d 条；国际服未提供路径' % c}
    return {'go': 'unknown', 'why': '两个服的路径都没给，无法检查'}


def locate(needle, intl='', cn='', buckets=None, catdir='', cn_db='',
           keys='', cn_keys=''):
    """一次问清「这个资源在哪个服、有多少、本地能不能拿」。

    为什么要这条命令：不先分辨服就开跑，会在没有这个活动的服上空转。
    MARIA-n 在国服清单里只有 9 个四周年小游戏音频，找立绘必然一无所获，
    而在国际服有 198 个包。两边的口径完全不同：国际服查七桶 catalog，
    国服查 Addressables 清单 + 本地缓存索引，这里把它们对齐到同一个关键词。
    """
    low = needle.lower()
    rep = {'needle': needle, 'servers': {}}

    if intl:
        try:
            hit, miss = find_keys(intl, needle, buckets or INTL_BUCKETS, catdir=catdir)
            flats = {b: len(v) for b, v in hit.items()}
            node = {'checked': True, 'total': sum(flats.values()), 'buckets': flats,
                    'kinds': _kinds([k for b in hit for k in hit[b]], sep='_assets_'),
                    'samples': [k for b in sorted(hit) for k in hit[b]][:5]}
            if miss:
                node['skipped'] = [{'bucket': b, 'why': w} for b, w in miss[:6]]
            if keys and hit:
                node['keys_files'] = write_keys(hit, keys)
                node['note'] = 'batch 一次只吃一个桶，按文件分别跑'
            rep['servers']['intl'] = node
        except Exception as e:
            rep['servers']['intl'] = {'checked': True, 'total': 0,
                                      'error': '%s: %s' % (type(e).__name__, e)}
    else:
        rep['servers']['intl'] = {'checked': False, 'why': '未提供 --intl-root'}

    if cn:
        try:
            ids, cat = cn_ids(cn)
            hits = []
            with open(ids, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and low in line.lower():
                        hits.append(line)
            objs = [cn_objname(h) for h in hits if h.endswith('.bundle')]
            db = cn_db or os.path.join('build', 'cn_index.sqlite')
            local = 0
            if objs and os.path.exists(db):
                import sqlite3
                con = sqlite3.connect('file:%s?mode=ro' % db.replace(os.sep, '/'), uri=True)
                try:
                    local = sum(1 for o in objs
                                if con.execute('SELECT 1 FROM files WHERE name=? LIMIT 1',
                                               (o,)).fetchone())
                finally:
                    con.close()
            node = {'checked': True, 'catalog': cat, 'total': len(hits),
                    'bundles': len(objs), 'local_bundles': local,
                    'kinds': _kinds(objs), 'samples': objs[:5]}
            if objs and not os.path.exists(db):
                node['index'] = '索引未建，只确认清单里有；建索引才知道本地是否已下载'
            if cn_keys and objs:
                d = os.path.dirname(os.path.abspath(cn_keys))
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(cn_keys, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('\n'.join(objs) + '\n')
                node['keys_file'] = cn_keys
            rep['servers']['cn'] = node
        except Exception as e:
            rep['servers']['cn'] = {'checked': True, 'total': 0,
                                    'error': '%s: %s' % (type(e).__name__, e)}
    else:
        rep['servers']['cn'] = {'checked': False, 'why': '未提供 --cn-root'}

    rep['verdict'] = _verdict(rep['servers'])
    return rep


def intl_root(root):
    """客户端根 -> com.shiftup.patch 目录（PC 的根在启动器指定位置，不在安装目录）。"""
    for cand in (os.path.join(root, 'com.shiftup.patch'),
                 os.path.join(root, 'Unity', 'com_proximabeta_NIKKE', 'com.shiftup.patch'),
                 root):
        if os.path.isdir(cand) and os.path.exists(os.path.join(cand, 'core', 'catalog.ndb')):
            return cand
    raise FileNotFoundError('找不到 com.shiftup.patch: %s' % root)


def intl_fetch(root, bucket, key, adb=False):
    """按完整键取 bundle 字节。

    adb=True 时 root 传设备侧 com.shiftup.patch 绝对路径：
    清单与索引先拉到本地解一次，数据体只在需要时用 dd 定点读，绝不整桶拉。
    """
    if adb:
        dev_patch = root.rstrip('/')
        cat = _ensure_cat(root, bucket, adb=True)
        idx_path = os.path.join('build', '_cat_adb', '%s.cdb.idx' % bucket)
        if not os.path.exists(idx_path):
            _adb_pull('%s/%s/chunk/store.cdb.idx' % (dev_patch, bucket), idx_path)
        store = '%s/%s/chunk/store.cdb' % (dev_patch, bucket)
    else:
        cat = _ensure_cat(root, bucket)
        patch = intl_root(root)
        store = os.path.join(patch, bucket, 'chunk', 'store.cdb')
        idx_path = os.path.join(patch, bucket, 'chunk', 'store.cdb.idx')
    import sqlite3
    con = sqlite3.connect(cat)
    row = con.execute('SELECT file_id FROM files_chunktype WHERE key=?', (key,)).fetchone()
    if not row:
        raise KeyError('清单里没有这个键: %s' % key)
    fid = row[0]
    segs = con.execute(
        'SELECT c.hash, c.original_size FROM chunk_file_map m JOIN chunks c ON c.chunk_id=m.chunk_id '
        'WHERE m.file_id=? ORDER BY m.file_offset', (fid,)).fetchall()
    idx = load_cidx(idx_path)
    dctx = zstd.ZstdDecompressor()
    buf = bytearray()
    for h, orig in segs:
        if h not in idx:
            raise KeyError('chunk 不在 idx（物理缺失，只能靠游戏内按需下载）: %s' % h.hex())
        pos, size = idx[h]
        blob = _adb_dd(store, pos, size) if adb else _read_store(store, pos, size)
        data = dctx.decompress(blob, max_output_size=orig) if size != orig else blob
        if len(data) != orig:
            raise ValueError('解压长度不符 %d != %d' % (len(data), orig))
        buf += data
    return bytes(buf), len(segs)


def _adb_pull(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out = subprocess.run(['adb', 'pull', src, dst], capture_output=True, text=True).stdout
    if not os.path.exists(dst):
        raise RuntimeError('adb pull 失败: %s\n%s' % (src, out))


def _read_store(path, pos, size):
    with open(path, 'rb') as f:
        f.seek(pos)
        return f.read(size)


def _adb_dd(dev_path, pos, size):
    """exec-out + skip_bytes,count_bytes：adb shell 会把 dd 统计行混进 stdout。"""
    cmd = ['adb', 'exec-out',
           'dd if=%s bs=4096 skip=%d count=%d iflag=skip_bytes,count_bytes 2>/dev/null'
           % (dev_path, pos, size)]
    out = subprocess.run(cmd, capture_output=True).stdout
    if len(out) != size:
        raise ValueError('dd 长度不符 %d != %d（pos=%d）' % (len(out), size, pos))
    return out


# ---------------------------------------------------------------- 国服：缓存索引

def path_key(p):
    """续跑去重键：绝对化 + 反斜杠统一 + 小写。

    只用 normpath 不够——`E:/x`、`E:\\x`、`e:\\x` 是同一个文件但三个字符串，
    done 表按字符串比对会让续跑永远失效、每次都全量重跑。
    """
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def cn_cache_paths(cache_root):
    """cache/<hashA>/<hashB>/__data —— 三层，别漏最后一层。"""
    root = os.path.abspath(cache_root)
    for a in os.listdir(root):
        pa = os.path.join(root, a)
        if not os.path.isdir(pa):
            continue
        for b in os.listdir(pa):
            p = os.path.join(pa, b, '__data')
            if os.path.isfile(p):
                yield p


def cn_index(cache_root, db_path, jobs=4, resume=True, limit_mb=256):
    """建「包内对象名 -> __data 路径」索引，落 sqlite，可中断续跑。

    为什么不用 json：两万包、几十万条对象名，json 每次要整体 load 再 O(n) 扫子串；
    sqlite 有主键索引，精确命中走 B 树，不用把整个索引读进内存。

    为什么必须进程隔离：实测有单个 39 KB 的包能让 UnityPy 直接段错误（SIGSEGV）。
    Python 抓不住信号级崩溃，一段代码里跑就会连累整个进程，前面几万包的成果全丢，
    而且 Pool 的 worker 崩了之后主进程会卡在等结果上——这正是「跑 40 分钟不收敛」的真因。
    所以每个分片交给独立子进程，崩了只损失当前包，主进程记账后继续。

    续跑去重键用 path_key()：`E:/x` 与 `E:\\x` 是同一文件不同字符串，
    按原样比对会让续跑永远命不中、每次全量重跑。
    """
    import sqlite3

    paths = list(cn_cache_paths(cache_root))
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS files('
                'name TEXT NOT NULL, path TEXT NOT NULL, primary key(name, path))')
    con.execute('CREATE INDEX IF NOT EXISTS ix_name ON files(name)')
    con.execute('CREATE TABLE IF NOT EXISTS done(path TEXT PRIMARY KEY)')
    con.commit()
    done = set(r[0] for r in con.execute('SELECT path FROM done')) if resume else set()
    con.close()

    todo = [p for p in paths if path_key(p) not in done]
    total = len(todo)
    if not total:
        return {'bundles': 0, 'names': 0, 'skipped': 0, 'seconds': 0.0, 'note': '无待处理'}
    if jobs < 1:
        jobs = 1

    t0 = time.time()
    # 交错切分：相邻路径常同属一个大目录，按块切会让某个分片全是大包
    parts = [todo[i::jobs] for i in range(min(jobs, total))]
    os.makedirs('build/_cnparts', exist_ok=True)
    procs, handles = [], []
    for i, part in enumerate(parts):
        pf = os.path.join('build', '_cnparts', 'p%d.txt' % i)
        pd = os.path.join('build', '_cnparts', 'p%d.sqlite' % i)
        if os.path.exists(pd):
            os.remove(pd)
        with open(pf, 'w', encoding='utf-8') as f:
            f.write('\n'.join(part))
        procs.append((i, part, pf, pd))

    print('  待处理 %d 包，切 %d 片' % (total, len(procs)), file=sys.stderr, flush=True)
    for i, part, pf, pd in procs:
        handles.append(subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), '_cnpart', pf, pd],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    bad_parts = []
    for (i, part, pf, pd), h in zip(procs, handles):
        rc = h.wait()
        if rc != 0:
            bad_parts.append((i, part, pd))
            print('  分片 %d 退出码 %d（疑似毒包段错误），转逐包隔离' % (i, rc),
                  file=sys.stderr, flush=True)

    # 收编各分片
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA journal_mode=WAL')
    merged = 0
    for i, part, pf, pd in procs:
        if not os.path.exists(pd):
            continue
        con.execute("ATTACH DATABASE ? AS s%d" % i, (os.path.abspath(pd),))
        con.execute('INSERT OR IGNORE INTO files(name, path) SELECT name, path FROM s%d.files' % i)
        con.execute('INSERT OR IGNORE INTO done(path) SELECT path FROM s%d.done' % i)
        merged += con.execute('SELECT count(*) FROM s%d.done' % i).fetchone()[0]
        con.commit()
        con.execute('DETACH DATABASE s%d' % i)

    # 崩掉的分片：逐包开子进程补，毒包标记跳过
    rescued = killed = 0
    for i, part, pd in bad_parts:
        done2 = set(r[0] for r in con.execute('SELECT path FROM done'))
        for p in part:
            if path_key(p) in done2:
                continue
            rc = subprocess.run(
                [sys.executable, os.path.abspath(__file__), '_cnpart', '-', db_path, p],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode
            if rc == 0:
                rescued += 1
            else:
                killed += 1
                con.execute('INSERT OR IGNORE INTO done(path) VALUES(?)', (path_key(p),))
                con.commit()
                print('  毒包（段错误，已标记跳过）: %s' % p, file=sys.stderr, flush=True)

    n_names = con.execute('SELECT count(DISTINCT name) FROM files').fetchone()[0]
    n_done = con.execute('SELECT count(*) FROM done').fetchone()[0]
    con.close()
    return {'bundles': n_done, 'names': n_names, 'skipped': killed,
            'rescued': rescued, 'poison_parts': len(bad_parts),
            'seconds': round(time.time() - t0, 1)}


def _cn_part(paths_file, db_path, single=''):
    """子进程入口：处理一份路径清单，写独立 sqlite，每包 commit。

    段错误只会带走当前这一个包，前面已 commit 的进度都在。
    传 single 时只处理这一个包（用于毒包定位）。
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS files('
                'name TEXT NOT NULL, path TEXT NOT NULL, primary key(name, path))')
    con.execute('CREATE TABLE IF NOT EXISTS done(path TEXT PRIMARY KEY)')
    con.commit()
    done = set(r[0] for r in con.execute('SELECT path FROM done'))

    if single:
        paths = [single]
    else:
        with open(paths_file, encoding='utf-8') as f:
            paths = [x.strip() for x in f if x.strip()]

    for p in paths:
        k = path_key(p)
        if k in done:
            continue
        path, names, size = _probe_bundle(p)
        if names:
            con.executemany('INSERT OR IGNORE INTO files(name, path) VALUES(?,?)',
                            [(n, path) for n in names])
        con.execute('INSERT OR IGNORE INTO done(path) VALUES(?)', (k,))
        con.commit()
    con.close()
    return 0


def _probe_bundle(path):
    """worker：返回 (路径, 对象名列表, 字节数)。解不动就返回 None，让主进程记账跳过。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return (path, None, 0)
    if size > 256 * 2 ** 20:      # 已知本机最大 109MB；过大直接跳过防拖尾
        return (path, None, size)
    try:
        import UnityPy
        env = UnityPy.load(path)
        out = []
        for o in env.objects:
            try:
                n = o.read().m_Name
            except Exception:
                continue
            if n:
                out.append(n)
            if len(out) >= 400:
                break
        return (path, out, size)
    except Exception:
        return (path, None, size)


def _container_keys(path):
    """兼容旧调用：只要对象名列表。"""
    return _probe_bundle(path)[1] or []


def cn_fetch(cache_root, needle, out_path, nau=None, db_path=None, strict=False):
    """按对象名定位 bundle，必要时过 NAU 解 NKAB。

    `needle` 可以是完整对象名（清单键末 32 hex + .bundle），也可以是片段。
    精确命中优先；未命中再退回 LIKE 模糊，并把候选数回报出来，方便判断是不是版本变了。
    `strict=True` 时不做模糊回退——批量场景必须如此：一句 LIKE 取第一条，
    出错不报错，只是悄悄导出另一个包，比失败更难发现。
    """
    import sqlite3
    db_path = db_path or os.path.join('build', 'cn_index.sqlite')
    if not os.path.exists(db_path):
        print('[索引不存在，先建一次]', file=sys.stderr)
        cn_index(cache_root, db_path)
    con = sqlite3.connect('file:%s?mode=ro' % db_path.replace(os.sep, '/'), uri=True)

    hit = None
    for cand in (needle, needle + '.bundle'):
        hit = con.execute('SELECT name, path FROM files WHERE name=? LIMIT 1', (cand,)).fetchone()
        if hit:
            break
    n_cand = 1
    if not hit:
        if strict:
            con.close()
            raise KeyError('索引里没有该对象名: %s' % needle)
        rows = con.execute('SELECT name, path FROM files WHERE name LIKE ? LIMIT 50',
                           ('%' + needle + '%',)).fetchall()
        if not rows:
            raise KeyError('索引里没有命中: %s（确认版本是否变了，或索引是否覆盖该包）' % needle)
        hit = rows[0]
        n_cand = len(rows)
    con.close()

    name, src = hit
    data = open(src, 'rb').read()
    head = data[:4].hex()
    if data[:4] == b'NKAB':
        if not nau:
            raise RuntimeError('该包是 NKAB 密文，需要 --nau 指向 NAU.exe')
        data = nau_decrypt(nau, src, out_path)
        head += ' -> UnityFS'
    else:
        open(out_path, 'wb').write(data)
    return {'container': name, 'src': src, 'bytes': len(data), 'head': head,
            'candidates': n_cand}


def nau_decrypt(nau, src, dst):
    """NAU 会停在 Press enter，必须给空 stdin。"""
    tmp = dst + '.nau'
    subprocess.run([nau, 'd', '-i', src, '-o', tmp],
                   stdin=subprocess.DEVNULL, capture_output=True)
    data = open(tmp, 'rb').read()
    os.replace(tmp, dst)
    return data


# ---------------------------------------------------------------- 导出

def export(bundle, out_dir, only=''):
    """UnityPy 导出 + 自检。看不到数字就当失败。

    `only` 是逗号分隔的关键词白名单，只落名字命中的对象。
    活动 UI 常与公共元素（`ele_*` / `fx_*` / `common_*`）打进同一张图集，
    整包导出会把别的活动的东西一起带出来——实测 TRUE FLAVOR 用了 22 个包，
    导出 381 张图，其中大半与活动无关，入库前还得手工挑。
    """
    import UnityPy
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    want = [w.strip().lower() for w in only.split(',') if w.strip()]
    stats = {'Texture2D': 0, 'Sprite': 0, 'TextAsset': 0, 'AudioClip': 0, 'Mesh': 0,
             'kept': 0, 'skipped': 0}
    sizes = []
    for o in env.objects:
        t = o.type.name
        try:
            d = o.read()
        except Exception:
            continue
        name = getattr(d, 'm_Name', None) or str(o.path_id)
        if want and not any(w in name.lower() for w in want):
            stats['skipped'] += 1
            continue
        if t in stats:
            stats[t] += 1
        stats['kept'] += 1
        safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)[:80]
        if t == 'Texture2D':
            try:
                img = d.image
                img.save(os.path.join(out_dir, safe + '.png'))
                sizes.append('%dx%d' % img.size)
            except Exception:
                pass
        elif t == 'TextAsset':
            raw = d.m_Script
            raw = raw if isinstance(raw, bytes) else raw.encode('utf-8', 'surrogateescape')
            # Spine 的 .skel/.atlas 也是 TextAsset，名字里自带扩展名。
            # 一律补 .txt 会导出 xxx.skel.txt，入库前还得手动改名，容易漏。
            ext = os.path.splitext(safe)[1].lower()
            fn = safe if ext in ('.skel', '.atlas', '.json', '.txt', '.bytes', '.csv', '.xml') \
                else safe + '.txt'
            open(os.path.join(out_dir, fn), 'wb').write(raw)
        elif t == 'AudioClip':
            try:
                for n, wav in d.samples.items():
                    open(os.path.join(out_dir, safe + '.wav'), 'wb').write(wav)
            except Exception:
                pass
    stats['sizes'] = sorted(set(sizes))[:5]
    return stats


def _safe(name):
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)[:80]


def pull(scene, root, key, out_dir, bucket='core', nau='', adb=None, strict=False, only=''):
    """取件 + 导出，一条命令、一次进程。

    为什么合并：单件取件的固定成本几乎全是进程启动，实测
    `python -c pass` 294ms、`import UnityPy` 约 1750ms，而真正读写解压只有几十到几百毫秒。
    拆成 get 和 export 两条命令，等于把这笔固定成本付两遍。
    中间 bundle 默认不落盘，要留用 keep_bundle。
    """
    import shutil
    import tempfile

    adb = scene.endswith('adb') if adb is None else adb
    tmp = tempfile.mkdtemp(prefix='nk_pull_')
    try:
        bundle = os.path.join(tmp, 'x.bundle')
        if scene.startswith('intl'):
            data, nseg = intl_fetch(root, bucket, key, adb=adb)
            open(bundle, 'wb').write(data)
            info = {'bytes': len(data), 'segments': nseg}
        else:
            info = cn_fetch(root, key, bundle, nau, strict=strict)
        info.update(export(bundle, out_dir, only=only))
        info['out'] = out_dir
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _pull_job(args):
    """worker：多进程时每个进程自己 import 一次 UnityPy，然后连跑多件。"""
    scene, root, key, out_dir, bucket, nau, adb, strict, only = args
    try:
        r = pull(scene, root, key, out_dir, bucket=bucket, nau=nau, adb=adb,
                 strict=strict, only=only)
        return {'key': key, 'bytes': r.get('bytes'), 'sizes': r.get('sizes'),
                'kept': r.get('kept'), 'skipped': r.get('skipped'), 'err': None}
    except Exception as e:
        return {'key': key, 'bytes': None, 'sizes': None, 'kept': None, 'skipped': None,
                'err': '%s: %s' % (type(e).__name__, e)}


def preflight(scene, keys, root='', bucket='core', adb=None, catdir=''):
    """跑之前先分清「能拉」和「物理没有」。

    清单记录的是「这个版本下发过什么」，而 chunk 只有在玩家真要这份资源时
    才被下进 store.cdb。所以「清单里有」不等于「本地有」——实测一个活动
    109 个 dp 键里 54 个属于后者，且全是 sd 变体。
    不预检就要等整批跑完、看失败统计才知道，白付一遍导出开销。
    """
    import sqlite3
    adb = scene.endswith('adb') if adb is None else adb
    cat = _ensure_cat(root, bucket, adb=adb, catdir=catdir)
    if adb:
        idx_path = os.path.join('build', '_cat_adb', '%s.cdb.idx' % bucket)
        if not os.path.exists(idx_path):
            _adb_pull('%s/%s/chunk/store.cdb.idx' % (root.rstrip('/'), bucket), idx_path)
    else:
        patch = intl_root(root)
        idx_path = os.path.join(patch, bucket, 'chunk', 'store.cdb.idx')
    idx = load_cidx(idx_path)

    con = sqlite3.connect('file:%s?mode=ro' % cat.replace(os.sep, '/'), uri=True)
    ok, gone, unknown = [], [], []
    try:
        for k in keys:
            row = con.execute('SELECT file_id FROM files_chunktype WHERE key=?', (k,)).fetchone()
            if not row:
                unknown.append(k)
                continue
            hashes = [r[0] for r in con.execute(
                'SELECT c.hash FROM chunk_file_map m JOIN chunks c ON c.chunk_id=m.chunk_id '
                'WHERE m.file_id=?', (row[0],))]
            lack = [h for h in hashes if h not in idx]
            if lack:
                gone.append({'key': k, 'chunks': [h.hex()[:16] for h in lack[:3]],
                             'n': len(lack)})
            else:
                ok.append(k)
    finally:
        con.close()
    return {'keys': len(keys), 'ok': ok, 'gone': gone, 'unknown': unknown}


def _read_keys(path):
    """读键表：一行一个键，空行跳过，`# `（井号+空格）开头为注释。

    这里刻意不做 strip。国服真实存在以空格开头的对象名（` sound_hacking_active`），
    strip 掉就永远查不到；注释也只认 `# `，因为国服有 `##_board_touchtext` 这类名字。
    国际服的键不含空格，调用方自行 strip 一次兜手抄误差。
    """
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            s = line.rstrip('\r\n')
            t = s.strip()
            if not t or t == '#' or t.startswith('# ') or t.startswith('#\t'):
                continue
            out.append(s)
    return out


def cn_preflight(keys, db=None):
    """国服预检：把「索引里没有这个名字」的挑出来。

    国服取件是整文件复制，不存在「块没下载」这回事，能查的只有对象名在不在索引里。
    判据与取件同一条：name 精确匹配。顺带统计同名多包——一个对象名可能出现在
    多个包里（Unity 允许重名），取件只取第一条，数量多时值得知道。
    """
    import sqlite3
    db = db or os.path.join('build', 'cn_index.sqlite')
    if not os.path.exists(db):
        raise FileNotFoundError('国服索引不存在: %s' % db)
    con = sqlite3.connect('file:%s?mode=ro' % db.replace(os.sep, '/'), uri=True)
    ok, unknown, multi = [], [], []
    try:
        for k in keys:
            hit = None
            for cand in (k, k.strip()):
                if cand and con.execute('SELECT 1 FROM files WHERE name=? LIMIT 1',
                                        (cand,)).fetchone():
                    hit = cand
                    break
            if not hit:
                unknown.append(k)
                continue
            rows = con.execute('SELECT path FROM files WHERE name=? LIMIT 2', (hit,)).fetchall()
            if len(rows) > 1:
                multi.append(hit)
            ok.append(hit)
    finally:
        con.close()
    return {'keys': len(keys), 'ok': ok, 'unknown': unknown, 'multi': multi}


def batch(scene, root, keys_file, out_root, bucket='core', nau='', adb=None,
          limit=0, jobs=1, precheck=True, skip_missing=False, db='', only=''):
    """批量取件导出：一次进程吃一整份键表。

    省的是每件约 2 秒的解释器 + UnityPy 导入。键表一行一个完整键，`#` 开头为注释。
    失败不中断，逐条记账，最后统一回报。

    jobs>1 时按件多进程：每个 worker 各付一次导入，但导入是并行发生的，
    wall time 只算一次，再乘上按件并行。件数少于 2×jobs 时退回串行，否则 spawn 开销吃掉收益。

    precheck 先按 idx 分「能拉 / 物理没有」；skip_missing 时只拉能拉的。
    国服没有 idx，预检改为查索引里有没有这个对象名，其余流程一致；
    键是对象名（不带扩展名），取件走整文件复制，NKAB 才需要 --nau。
    """
    keys = _read_keys(keys_file)
    if scene.startswith('intl'):
        keys = [k.strip() for k in keys]
    if limit:
        keys = keys[:limit]

    pre = None
    if precheck and scene.startswith('intl'):
        pre = preflight(scene, keys, root=root, bucket=bucket, adb=adb)
        print('预检: 键 %d  可拉 %d  物理缺失 %d  清单无此键 %d'
              % (pre['keys'], len(pre['ok']), len(pre['gone']), len(pre['unknown'])),
              file=sys.stderr, flush=True)
        for g in pre['gone'][:5]:
            print('  缺 %d 块  %s' % (g['n'], g['key']), file=sys.stderr)
        if len(pre['gone']) > 5:
            print('  …另外 %d 个同样缺块' % (len(pre['gone']) - 5), file=sys.stderr)
        if skip_missing:
            keys = pre['ok']
            if not keys:
                return {'total': 0, 'ok': 0, 'fail': 0, 'seconds': 0.0, 'jobs': 1,
                        'per_item_ms': 0, 'failures': [], 'note': '预检后无可拉键'}
    elif precheck and scene.startswith('cn'):
        try:
            pre = cn_preflight(keys, db=db)
        except FileNotFoundError as e:
            print('预检跳过：%s' % e, file=sys.stderr, flush=True)
        else:
            print('预检: 键 %d  索引有 %d  索引没有 %d  同名多包 %d'
                  % (pre['keys'], len(pre['ok']), len(pre['unknown']), len(pre['multi'])),
                  file=sys.stderr, flush=True)
            for k in pre['unknown'][:5]:
                print('  索引无此名  %s' % k, file=sys.stderr)
            if len(pre['unknown']) > 5:
                print('  …另外 %d 个同样查不到' % (len(pre['unknown']) - 5), file=sys.stderr)
            if skip_missing:
                keys = pre['ok']
                if not keys:
                    return {'total': 0, 'ok': 0, 'fail': 0, 'seconds': 0.0, 'jobs': 1,
                            'per_item_ms': 0, 'failures': [], 'note': '预检后无可取键'}

    total = len(keys)
    t0 = time.time()
    ok, fail = [], []
    # 国服必须严格精确：一句 LIKE 取第一条不会报错，只会悄悄导出别的包。
    strict = scene.startswith('cn')

    def record(i, r):
        if r['err']:
            fail.append({'key': r['key'], 'err': r['err']})
        else:
            ok.append({'key': r['key'], 'bytes': r['bytes'], 'sizes': r['sizes'],
                       'kept': r.get('kept'), 'skipped': r.get('skipped')})
        if i % 10 == 0 or i == total:
            print('  %d/%d  %.1fs  失败 %d' % (i, total, time.time() - t0, len(fail)),
                  file=sys.stderr, flush=True)

    if jobs > 1 and total >= 2 * jobs:
        import multiprocessing as mp
        tasks = [(scene, root, k, os.path.join(out_root, _safe(k)), bucket, nau, adb, strict, only)
                 for k in keys]
        with mp.Pool(jobs) as pool:
            for i, r in enumerate(pool.imap_unordered(_pull_job, tasks, chunksize=2), 1):
                record(i, r)
    else:
        for i, k in enumerate(keys, 1):
            record(i, _pull_job((scene, root, k, os.path.join(out_root, _safe(k)),
                                 bucket, nau, adb, strict, only)))

    el = time.time() - t0
    rep = {'total': total, 'ok': len(ok), 'fail': len(fail),
           'seconds': round(el, 1), 'jobs': jobs if (jobs > 1 and total >= 2 * jobs) else 1,
           'per_item_ms': round(el / total * 1000) if total else 0,
           'failures': fail[:20]}
    if only:
        rep['only'] = only
        rep['kept'] = sum(o['kept'] or 0 for o in ok)
        rep['skipped'] = sum(o['skipped'] or 0 for o in ok)
    if pre:
        if scene.startswith('intl'):
            rep['preflight'] = {'keys': pre['keys'], 'pullable': len(pre['ok']),
                                'missing': len(pre['gone']), 'unknown': len(pre['unknown']),
                                'skipped_missing': bool(skip_missing)}
        else:
            rep['preflight'] = {'keys': pre['keys'], 'pullable': len(pre['ok']),
                                'not_in_index': len(pre['unknown']),
                                'multi_path': len(pre['multi']),
                                'skipped_missing': bool(skip_missing)}
    return rep



# ---------------------------------------------------------------- 自检

def doctor(scene, root):
    rep = {'scene': scene, 'root': root, 'checks': []}

    def add(name, ok, detail=''):
        rep['checks'].append({'item': name, 'ok': bool(ok), 'detail': detail})

    if scene.endswith('adb'):
        out = subprocess.run(['adb', 'devices'], capture_output=True, text=True).stdout
        add('adb 设备', 'device' in out.replace('unauthorized', ''), out.strip().splitlines()[-1] if out else '')
        pkg = 'com.proximabeta.nikke' if scene.startswith('intl') else 'com.tencent.nikke'
        v = subprocess.run(['adb', 'shell', 'dumpsys package %s | grep versionName' % pkg],
                           capture_output=True, text=True).stdout.strip()
        add('版本三要素', bool(v), v)
    if scene.startswith('intl'):
        try:
            if scene.endswith('adb'):
                out = subprocess.run(['adb', 'shell', 'ls %s' % root.rstrip('/')],
                                     capture_output=True, text=True).stdout.split()
                add('七桶齐全', 'core' in out, ','.join(out[:8]))
            else:
                patch = intl_root(root)
                buckets = [b for b in ('core', 'dp', 'fd', 'en', 'ja', 'ko', 'saus')
                           if os.path.isdir(os.path.join(patch, b))]
                add('七桶齐全', len(buckets) == 7, ','.join(buckets))
                cat = os.path.join(patch, 'core', 'catalog.ndb')
                add('core 清单', os.path.exists(cat),
                    '%d B' % os.path.getsize(cat) if os.path.exists(cat) else '')
        except Exception as e:
            add('国际服根', False, str(e))
    else:
        if scene.endswith('adb'):
            base = root.rstrip('/')
            out = subprocess.run(['adb', 'shell', 'ls %s/UnityCache/Shared | wc -l' % base],
                                 capture_output=True, text=True).stdout.strip()
            add('缓存条目', out.isdigit() and int(out) > 0, out)
            js = subprocess.run(['adb', 'shell', 'ls %s/com.unity.addressables | wc -l' % base],
                                capture_output=True, text=True).stdout.strip()
            add('清单目录', js.isdigit() and int(js) > 0, js + ' 个文件')
        else:
            n = sum(1 for _ in cn_cache_paths(root))
            add('缓存条目', n > 0, str(n))
            js = os.path.join(os.path.expandvars(r'%USERPROFILE%'),
                              'AppData', 'LocalLow', 'com_tencent')
            add('清单目录', os.path.isdir(js), js)
    for mod in ('UnityPy', 'zstandard', 'PIL'):
        try:
            __import__(mod)
            add('依赖 ' + mod, True)
        except ImportError:
            add('依赖 ' + mod, False, '未安装')
    rep['pass'] = all(c['ok'] for c in rep['checks'])
    return rep


def main():
    ap = argparse.ArgumentParser(prog='nk')
    ap.add_argument('cmd', choices=['doctor', 'scan', 'find', 'get', 'pull', 'batch',
                                    'locate', 'cnindex', 'cnget', 'export', '_cnpart'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--scene', default='intl-pc')
    ap.add_argument('--root', default='')
    ap.add_argument('--bucket', default='core')
    ap.add_argument('--out', '-o', default='')
    ap.add_argument('--nau', default='')
    ap.add_argument('--db', default='', help='国服索引库路径，默认 build/cn_index.sqlite')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--all', action='store_true', help='find: 遍历全部七桶，不截断')
    ap.add_argument('--keys', default='', help='find: 把结果写成键表，供 batch 直接消费')
    ap.add_argument('--cat', default='', help='find: 复用已解密的 catalog 目录，跳过重新解包')
    ap.add_argument('--no-precheck', action='store_true', help='batch: 跳过 idx 预检')
    ap.add_argument('--skip-missing', action='store_true', help='batch: 预检后只拉能拉的')
    ap.add_argument('--intl-root', default='', help='locate: 国际服客户端根（PC）')
    ap.add_argument('--cn-root', default='', help='locate: 国服根，cache/nikke_Data/安装目录皆可')
    ap.add_argument('--cn-keys', default='', help='locate: 把国服命中对象名写成清单')
    ap.add_argument('--only', default='', help='pull/batch: 只导出名字含这些关键词的对象，逗号分隔')
    a = ap.parse_args()
    need = {'find': 1, 'get': 1, 'pull': 1, 'batch': 1, 'cnget': 1, 'export': 1,
            'locate': 1, '_cnpart': 2}
    if a.cmd in need and len(a.args) < need[a.cmd]:
        ap.error('%s 需要 %d 个位置参数（键 / 键表路径 / bundle 路径）' % (a.cmd, need[a.cmd]))
    if a.cmd in ('pull', 'batch', 'export'):
        require('UnityPy', 'PIL')
    out = a.out

    if a.cmd == 'doctor':
        rep = doctor(a.scene, a.root)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep['pass'] else 2

    if a.cmd == 'scan':
        patch = intl_root(a.root)
        os.makedirs(os.path.join('build', '_cat'), exist_ok=True)
        rep = {}
        for b in ('core', 'dp', 'fd', 'en', 'ja', 'ko', 'saus'):
            src = os.path.join(patch, b, 'catalog.ndb')
            if not os.path.exists(src):
                continue
            dst = os.path.join('build', '_cat', '%s.sqlite' % b)
            r = nkdb_decrypt(src, dst)
            import sqlite3
            con = sqlite3.connect(dst)
            r['keys'] = con.execute('SELECT count(*) FROM files_chunktype').fetchone()[0]
            r['size'] = os.path.getsize(src)
            rep[b] = r
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    if a.cmd == 'find':
        if a.scene.startswith('cn'):
            # 国服缓存里只有「包内对象名 <32hex>.bundle」，没有语义键；
            # 按名检索要读 Addressables catalog（明文 JSON），不在本命令范围。
            print(json.dumps({'error': 'find 不支持国服',
                              'reason': '国服缓存索引只有对象名，没有可读的语义键',
                              'use': 'cnget --scene cn-pc <对象名片段>'}, ensure_ascii=False))
            return 3
        adb = a.scene.endswith('adb')
        buckets = INTL_BUCKETS if a.all else (a.bucket,)
        t0 = time.time()
        hit, miss = find_keys(a.root, a.args[0], buckets, adb=adb, catdir=a.cat)
        total = sum(len(v) for v in hit.values())
        rep = {'needle': a.args[0], 'total': total,
               'buckets': {b: len(v) for b, v in hit.items()},
               'ms': round((time.time() - t0) * 1000)}
        if miss:
            rep['skipped'] = [{'bucket': b, 'why': w} for b, w in miss]
        if a.keys and total:
            rep['keys_files'] = write_keys(hit, a.keys)
            if len(hit) > 1:
                rep['note'] = 'batch 一次只吃一个桶，按文件分别跑'
        if not a.keys and hit:
            lim = 0 if a.all else 40
            for b, ks in hit.items():
                print('== %s  %d' % (b, len(ks)))
                for k in (ks[:lim] if lim else ks):
                    print('  ', k)
            rep['listed'] = 'all' if a.all else min(40, total)
        print(json.dumps(rep, ensure_ascii=False))
        return 0 if total else 1

    if a.cmd == 'locate':
        rep = locate(a.args[0], intl=a.intl_root, cn=a.cn_root, catdir=a.cat,
                     cn_db=a.db, keys=a.keys, cn_keys=a.cn_keys)
        for key, label in (('intl', '国际服'), ('cn', '国服')):
            n = rep['servers'].get(key) or {}
            if not n.get('checked'):
                print('== %-4s 未检查（%s）' % (label, n.get('why', '')))
                continue
            if n.get('error'):
                print('== %-4s 失败：%s' % (label, n['error']))
                continue
            extra = ''
            if key == 'cn':
                extra = '  包 %d  本地已有 %d' % (n.get('bundles', 0), n.get('local_bundles', 0))
            elif n.get('buckets'):
                extra = '  ' + ' '.join('%s:%d' % kv for kv in sorted(n['buckets'].items()))
            print('== %-4s 命中 %d%s' % (label, n.get('total', 0), extra))
            if n.get('kinds'):
                print('    构成 %s' % ' '.join('%s:%d' % kv for kv in n['kinds'].items()))
            for s in n.get('samples', [])[:5]:
                print('    %s' % s)
            kf = n.get('keys_files')
            if isinstance(kf, dict):
                for b, p in sorted(kf.items()):
                    print('    键表 %s -> %s' % (b, p))
            elif kf:
                print('    清单 -> %s' % kf)
        print('>> 建议：%s  %s' % (rep['verdict']['go'], rep['verdict']['why']))
        print(json.dumps(rep, ensure_ascii=False))
        return 0 if rep['verdict']['go'] != 'none' else 1

    if a.cmd == 'get':
        key = a.args[0]
        data, n = intl_fetch(a.root, a.bucket, key, adb=a.scene.endswith('adb'))
        open(out or 'out.bundle', 'wb').write(data)
        print(json.dumps({'key': key, 'chunks': n, 'bytes': len(data),
                          'md5': hashlib.md5(data).hexdigest(), 'head': data[:4].decode('latin1')},
                         ensure_ascii=False))
        return 0

    if a.cmd == '_cnpart':
        # 内部子命令：不在文档里暴露。由 cnindex 起子进程调用，做进程隔离。
        return _cn_part(a.args[0], a.args[1], a.args[2] if len(a.args) > 2 else '')

    if a.cmd == 'cnindex':
        print(json.dumps(cn_index(a.root, out or 'build/cn_index.sqlite', a.jobs),
                         ensure_ascii=False))
        return 0

    if a.cmd == 'cnget':
        print(json.dumps(cn_fetch(a.root, a.args[0], out or 'out.bundle', a.nau,
                                  a.db or None), ensure_ascii=False))
        return 0

    if a.cmd == 'pull':
        print(json.dumps(pull(a.scene, a.root, a.args[0], out or 'out', a.bucket, a.nau,
                              only=a.only), ensure_ascii=False))
        return 0

    if a.cmd == 'batch':
        print(json.dumps(batch(a.scene, a.root, a.args[0], out or 'out', a.bucket,
                               a.nau, limit=a.limit, jobs=a.jobs,
                               precheck=not a.no_precheck, skip_missing=a.skip_missing,
                               db=a.db, only=a.only), ensure_ascii=False))
        return 0

    if a.cmd == 'export':
        print(json.dumps(export(a.args[0], out or 'out'), ensure_ascii=False))
        return 0
    return 3


if __name__ == '__main__':
    sys.exit(main())
