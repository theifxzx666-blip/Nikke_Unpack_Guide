# -*- coding: utf-8 -*-
"""NIKKE 拆包统一入口 —— 四场景：国际服/国服 × PC/安卓。

只用标准库 + zstandard + UnityPy + Pillow。国服的 NKAB 解密交给外部 NAU.exe。

    python nk.py doctor  --scene intl-pc --root <客户端根>
    python nk.py scan    --scene intl-pc --root <客户端根> --out build/
    python nk.py find    --scene intl-pc --root <客户端根> "c010_00"
    python nk.py get     --scene intl-pc --root <客户端根> "<完整键>" -o out.bundle
    python nk.py cnindex --root <cache 根> -o build/cn_index.json
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


def load_cidx(path):
    """CIDX -> {hash16: (pos, compressed_size)}。小端，与 NKDB 的大端相反。"""
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

def cn_cache_paths(cache_root):
    """cache/<hashA>/<hashB>/__data —— 三层，别漏最后一层。"""
    for a in os.listdir(cache_root):
        pa = os.path.join(cache_root, a)
        if not os.path.isdir(pa):
            continue
        for b in os.listdir(pa):
            p = os.path.join(pa, b, '__data')
            if os.path.isfile(p):
                yield p


def cn_index(cache_root, out_json, jobs=8):
    """建 container 键 -> __data 路径的索引。

    国服缓存目录名是随机 hash，与清单里的 bundle 名无确定关系（md5 各种变体实测均不命中），
    只能读包内 container 键反查。50 包/秒/进程，两万包单进程 7 分钟，多进程 1 分钟。
    """
    import multiprocessing as mp
    paths = list(cn_cache_paths(cache_root))
    with mp.Pool(jobs) as pool:
        rows = pool.map(_container_keys, paths, chunksize=64)
    index = {}
    for p, keys in zip(paths, rows):
        for k in keys:
            index.setdefault(k, p)
    json.dump(index, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False)
    return {'bundles': len(paths), 'keys': len(index)}


def _container_keys(path):
    """包内对象名。含两类：`<32hex>.bundle`（= 清单里 bundle 名的后缀）与资源名。

    m_Container 是 [[键, 条目], ...] 列表而非 dict，且 98% 的键是 32hex，
    所以真正可用于反查的是对象名，不是容器键。
    """
    out = []
    try:
        import UnityPy
        env = UnityPy.load(path)
        for o in env.objects:
            try:
                n = o.read().m_Name
            except Exception:
                continue
            if n:
                out.append(n)
            if len(out) >= 400:
                break
    except Exception:
        return []
    return out


def cn_fetch(cache_root, needle, out_path, nau=None):
    """按 container 键片段定位 bundle，必要时过 NAU 解 NKAB。"""
    idx_path = os.path.join('build', 'cn_index.json')
    if not os.path.exists(idx_path):
        cn_index(cache_root, idx_path)
    index = json.load(open(idx_path, encoding='utf-8'))
    # 清单键的后 32 hex 就是包内 `<hash>.bundle` 对象名，优先精确命中，再退回子串
    cands = [needle, needle + '.bundle']
    hits = [k for c in cands for k in index if k == c]
    if not hits:
        low = needle.lower()
        hits = sorted(k for k in index if low in k.lower())
    if not hits:
        raise KeyError('索引里没有命中: %s' % needle)
    src = index[hits[0]]
    data = open(src, 'rb').read()
    head = data[:4].hex()
    if data[:4] == b'NKAB':
        if not nau:
            raise RuntimeError('该包是 NKAB 密文，需要 --nau 指向 NAU.exe')
        data = nau_decrypt(nau, src, out_path)
        head += ' -> UnityFS'
    else:
        open(out_path, 'wb').write(data)
    return {'container': hits[0], 'src': src, 'bytes': len(data), 'head': head,
            'candidates': len(hits)}


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
    ap.add_argument('cmd', choices=['doctor', 'scan', 'find', 'get', 'cnindex', 'cnget', 'export'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--scene', default='intl-pc')
    ap.add_argument('--root', default='')
    ap.add_argument('--bucket', default='core')
    ap.add_argument('--out', '-o', default='')
    ap.add_argument('--nau', default='')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
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

    if a.cmd == 'cnindex':
        print(json.dumps(cn_index(a.root, out or 'build/cn_index.json', a.jobs), ensure_ascii=False))
        return 0

    if a.cmd == 'cnget':
        print(json.dumps(cn_fetch(a.root, a.args[0], out or 'out.bundle', a.nau), ensure_ascii=False))
        return 0

    if a.cmd == 'export':
        print(json.dumps(export(a.args[0], out or 'out'), ensure_ascii=False))
        return 0
    return 3


if __name__ == '__main__':
    sys.exit(main())
