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
import struct
import subprocess
import sys
import time
import zlib

import zstandard as zstd

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
        os.makedirs(os.path.join('build', '_cat_adb'), exist_ok=True)
        cat = os.path.join('build', '_cat_adb', '%s.sqlite' % bucket)
        if not os.path.exists(cat):
            tmp = os.path.join('build', '_cat_adb', '%s_catalog.ndb' % bucket)
            _adb_pull('%s/%s/catalog.ndb' % (dev_patch, bucket), tmp)
            nkdb_decrypt(tmp, cat)
        idx_path = os.path.join('build', '_cat_adb', '%s.cdb.idx' % bucket)
        if not os.path.exists(idx_path):
            _adb_pull('%s/%s/chunk/store.cdb.idx' % (dev_patch, bucket), idx_path)
        store = '%s/%s/chunk/store.cdb' % (dev_patch, bucket)
    else:
        patch = intl_root(root)
        cat = os.path.join('build', '_cat', '%s.sqlite' % bucket)
        if not os.path.exists(cat):
            os.makedirs(os.path.dirname(cat), exist_ok=True)
            nkdb_decrypt(os.path.join(patch, bucket, 'catalog.ndb'), cat)
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


def cn_fetch(cache_root, needle, out_path, nau=None, db_path=None):
    """按对象名定位 bundle，必要时过 NAU 解 NKAB。

    `needle` 可以是完整对象名（清单键末 32 hex + .bundle），也可以是片段。
    精确命中优先；未命中再退回 LIKE 模糊，并把候选数回报出来，方便判断是不是版本变了。
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

def export(bundle, out_dir):
    """UnityPy 导出 + 自检。看不到数字就当失败。"""
    import UnityPy
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    env = UnityPy.load(bundle)
    stats = {'Texture2D': 0, 'Sprite': 0, 'TextAsset': 0, 'AudioClip': 0, 'Mesh': 0}
    sizes = []
    for o in env.objects:
        t = o.type.name
        if t in stats:
            stats[t] += 1
        try:
            d = o.read()
        except Exception:
            continue
        name = getattr(d, 'm_Name', None) or str(o.path_id)
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
            open(os.path.join(out_dir, safe + '.txt'), 'wb').write(raw)
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


def pull(scene, root, key, out_dir, bucket='core', nau='', adb=None):
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
            info = cn_fetch(root, key, bundle, nau)
        info.update(export(bundle, out_dir))
        info['out'] = out_dir
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _pull_job(args):
    """worker：多进程时每个进程自己 import 一次 UnityPy，然后连跑多件。"""
    scene, root, key, out_dir, bucket, nau, adb = args
    try:
        r = pull(scene, root, key, out_dir, bucket=bucket, nau=nau, adb=adb)
        return {'key': key, 'bytes': r.get('bytes'), 'sizes': r.get('sizes'), 'err': None}
    except Exception as e:
        return {'key': key, 'bytes': None, 'sizes': None,
                'err': '%s: %s' % (type(e).__name__, e)}


def batch(scene, root, keys_file, out_root, bucket='core', nau='', adb=None,
          limit=0, jobs=1):
    """批量取件导出：一次进程吃一整份键表。

    省的是每件约 2 秒的解释器 + UnityPy 导入。键表一行一个完整键，`#` 开头为注释。
    失败不中断，逐条记账，最后统一回报。

    jobs>1 时按件多进程：每个 worker 各付一次导入，但导入是并行发生的，
    wall time 只算一次，再乘上按件并行。件数少于 2×jobs 时退回串行，否则 spawn 开销吃掉收益。
    """
    with open(keys_file, encoding='utf-8') as f:
        keys = [x.strip() for x in f if x.strip() and not x.lstrip().startswith('#')]
    if limit:
        keys = keys[:limit]
    total = len(keys)
    t0 = time.time()
    ok, fail = [], []

    def record(i, r):
        if r['err']:
            fail.append({'key': r['key'], 'err': r['err']})
        else:
            ok.append({'key': r['key'], 'bytes': r['bytes'], 'sizes': r['sizes']})
        if i % 10 == 0 or i == total:
            print('  %d/%d  %.1fs  失败 %d' % (i, total, time.time() - t0, len(fail)),
                  file=sys.stderr, flush=True)

    if jobs > 1 and total >= 2 * jobs:
        import multiprocessing as mp
        tasks = [(scene, root, k, os.path.join(out_root, _safe(k)), bucket, nau, adb)
                 for k in keys]
        with mp.Pool(jobs) as pool:
            for i, r in enumerate(pool.imap_unordered(_pull_job, tasks, chunksize=2), 1):
                record(i, r)
    else:
        for i, k in enumerate(keys, 1):
            record(i, _pull_job((scene, root, k, os.path.join(out_root, _safe(k)),
                                 bucket, nau, adb)))

    el = time.time() - t0
    return {'total': total, 'ok': len(ok), 'fail': len(fail),
            'seconds': round(el, 1), 'jobs': jobs if (jobs > 1 and total >= 2 * jobs) else 1,
            'per_item_ms': round(el / total * 1000) if total else 0,
            'failures': fail[:20]}



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
                                    'cnindex', 'cnget', 'export', '_cnpart'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--scene', default='intl-pc')
    ap.add_argument('--root', default='')
    ap.add_argument('--bucket', default='core')
    ap.add_argument('--out', '-o', default='')
    ap.add_argument('--nau', default='')
    ap.add_argument('--db', default='', help='国服索引库路径，默认 build/cn_index.sqlite')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    need = {'find': 1, 'get': 1, 'pull': 1, 'batch': 1, 'cnget': 1, 'export': 1,
            '_cnpart': 2}
    if a.cmd in need and len(a.args) < need[a.cmd]:
        ap.error('%s 需要 %d 个位置参数（键 / 键表路径 / bundle 路径）' % (a.cmd, need[a.cmd]))
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
        adb = a.scene.endswith('adb')
        if adb:
            os.makedirs(os.path.join('build', '_cat_adb'), exist_ok=True)
            cat = os.path.join('build', '_cat_adb', '%s.sqlite' % a.bucket)
            if not os.path.exists(cat):
                tmp = os.path.join('build', '_cat_adb', '%s_catalog.ndb' % a.bucket)
                _adb_pull('%s/%s/catalog.ndb' % (a.root.rstrip('/'), a.bucket), tmp)
                nkdb_decrypt(tmp, cat)
        else:
            patch = intl_root(a.root)
            cat = os.path.join('build', '_cat', '%s.sqlite' % a.bucket)
            if not os.path.exists(cat):
                nkdb_decrypt(os.path.join(patch, a.bucket, 'catalog.ndb'), cat)
        import sqlite3
        con = sqlite3.connect(cat)
        for fid, key in con.execute('SELECT file_id,key FROM files_chunktype WHERE key LIKE ? LIMIT 40',
                                    ('%' + a.args[0] + '%',)):
            print(fid, key)
        return 0

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
        print(json.dumps(pull(a.scene, a.root, a.args[0], out or 'out', a.bucket, a.nau),
                         ensure_ascii=False))
        return 0

    if a.cmd == 'batch':
        print(json.dumps(batch(a.scene, a.root, a.args[0], out or 'out', a.bucket,
                               a.nau, limit=a.limit, jobs=a.jobs), ensure_ascii=False))
        return 0

    if a.cmd == 'export':
        print(json.dumps(export(a.args[0], out or 'out'), ensure_ascii=False))
        return 0
    return 3


if __name__ == '__main__':
    sys.exit(main())
