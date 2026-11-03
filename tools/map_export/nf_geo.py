"""NightFire level containers and Eurocom geo files (read-only parsing, no rendering).

From default.xbe (addresses in .local/game.exe):
- Level container (FUN_000be910 states, FUN_000be630 entry reader, FUN_000be7b0 kind dispatch):
  u32 table size, u32 count, 0x18 bytes; entries from +0x20, 14 bytes each: u32 size, u8 kind, 8 hex digits of the
  sub-file's hashcode + NUL. Data from table size + 0x20, back to back. Kinds 0/2/11 and 1 (the level's own geo file,
  sets a level flag) go to the geo file loader FUN_000a6b20; 3/4/5, 6, 7, 8 go elsewhere (not decoded here).
- Geo file (FUN_000a6a80 / FUN_000a6820): u32 mode (0 = chunks back to back), then chunks with a u32 header,
  low 24 bits = size including the header, high 8 bits = type:
    0x0e header (FUN_000a5eb0)        0x10 texture table, 12-byte records, one per KXT
    0x18 KXT texture (FUN_000a6110)   0x0d KXE mesh, then 0x04 its entity record (FUN_000a6180 -> FUN_000de220)
    0x1a placement list (FUN_000a6550) 0x1d end
    0x05 / 0x21 / 0x26 / 0x27 / 0x2c / 0x2e / 0x0f: kept raw, not decoded (see README)
- KXE (FUN_000de220): "KXE" 06, then u32 words: [2] vertex count, [3] index count, [4] group count, [7] vertex
  flag (stride 0x20 instead of 0x1c, FUN_000e4f80), [9]/[10] a second vertex set (6 bytes a vertex, not decoded).
  Vertices from +0x60; indices (u16) at vertex end + 3; groups (12 bytes) at index end + 3 (the loader moves each
  block up to 4-byte alignment in place, FUN_000e4680 / FUN_000e4890).
- KXT (FUN_000ddf90 -> FUN_000e4400): "KXT" 06, words [2] frame bytes (+0x7f slack, the loader aligns to 128),
  [3] width, [4] height, [5] / [8] format, [6] mip levels, [9] frame count; name at +0x34; pixels at (0x15+frames)*4.
"""
import struct

CHUNK_NAMES = {0x0e: 'header', 0x10: 'texture_table', 0x18: 'texture', 0x0d: 'mesh', 0x04: 'entity',
               0x1a: 'placements', 0x1d: 'end'}


def read_container(data):
    size, count = struct.unpack_from('<II', data, 0)
    out, o, pos = [], 0x20, size + 0x20
    for _ in range(count):
        sz, kind = struct.unpack_from('<IB', data, o)
        out.append(dict(name=data[o + 5:o + 13].decode('ascii'), kind=kind, offset=pos, size=sz))
        pos += sz
        o += 14
    if pos != len(data):
        # Seen: the data ends 0x20 bytes before the file does (padding, not decoded).
        pass
    return out


def chunks(geo):
    mode = struct.unpack_from('<I', geo, 0)[0]
    if mode != 0:
        raise NotImplementedError('geo file mode %d (offset table) not handled' % mode)
    p = 4
    while p + 4 <= len(geo):
        h = struct.unpack_from('<I', geo, p)[0]
        size, t = h & 0xFFFFFF, h >> 24
        yield t, p, geo[p + 4:p + size]
        if size == 0 or t == 0x1d:
            return
        p += size


def cstr(b):
    return b.split(b'\0')[0].decode('latin1')


# Xbox D3DFORMAT chosen by FUN_000e4400 from the KXT fields
def kxt_format(w):
    fmt5, fmt8 = w[5], w[8]
    if fmt8 == 0:
        return {4: 'A4R4G4B4', 8: 'A8R8G8B8'}.get(fmt5, 'A1R5G5B5')
    return {1: 'DXT1', 2: 'DXT3', 3: 'DXT3', 4: 'DXT5', 5: 'DXT5'}.get(fmt8, 'unknown%d' % fmt8)


def parse_kxt(c):
    w = struct.unpack_from('<21I', c, 0)
    frames = max(1, w[9])
    t = dict(name=cstr(c[0x34:0x54]), width=w[3], height=w[4], format=kxt_format(w), mips=w[6], frames=w[9],
             fields=list(w[:12]), pixels=c[(0x15 + frames) * 4:(0x15 + frames) * 4 + w[2]], reference=None)
    if (w[0] & 0xFFFF0000) == 0x44540000:
        # "TD" reference (FUN_000ddf90): takes the texture in global slot w[0] & 0xffff, loaded by another geo file
        t['reference'] = w[0] & 0xFFFF
        t['pixels'] = b''
    return t


def parse_kxe(c):
    w = struct.unpack_from('<24I', c, 0)
    nv, ni, ng, flag = w[2], w[3], w[4], w[7]
    stride = 0x20 if flag else 0x1c
    v0 = 0x60
    verts = []
    for i in range(nv):
        o = v0 + i * stride
        x, y, z = struct.unpack_from('<3f', c, o)
        normal, color = struct.unpack_from('<II', c, o + 12)
        u, v = struct.unpack_from('<2f', c, o + stride - 8)
        verts.append((x, y, z, normal, color, u, v))
    i0 = v0 + nv * stride + 3
    idx = list(struct.unpack_from('<%dH' % ni, c, i0))
    g0 = i0 + ni * 2 + 3
    groups = []
    for g in range(ng):
        tex, tex2, tris, u3, flags, u5 = struct.unpack_from('<6H', c, g0 + g * 12)
        groups.append(dict(texture=tex, texture2=tex2, triangles=tris, flags=flags, unk=(u3, u5)))
    end = g0 + ng * 12
    return dict(fields=list(w[:12]), stride=stride, vertices=verts, indices=idx, groups=groups,
                tail=len(c) - end, extra_vertex_sets=(w[9], w[10]))


def parse_entity(c):
    hsh, flags = struct.unpack_from('<iI', c, 0)
    f = struct.unpack_from('<10f', c, 8)
    return dict(hash=hsh, flags=flags, sphere=f[0:4], bbox_min=f[4:7], bbox_max=f[7:10], name=cstr(c[0x30:]))


def parse_placements(c):
    out, q = [], 0
    while q + 0x4c <= len(c):
        ent, u1, hsh, flags = struct.unpack_from('<HHiI', c, q)
        f = struct.unpack_from('<6f', c, q + 0x0c)
        g = struct.unpack_from('<4f', c, q + 0x24)
        s = struct.unpack_from('<3f', c, q + 0x34)
        rest = c[q + 0x40:q + 0x48]
        n = struct.unpack_from('<I', c, q + 0x48)[0]
        params = [struct.unpack_from('<iI', c, q + 0x4c + k * 8) for k in range(n)]
        # a = position, b = Euler angles (both copied by FUN_000a6550), c = quaternion (= b in D3DX yaw-pitch-roll
        # order with the angles negated, checked on every rotated placement), s = scale (observed ~1)
        out.append(dict(entity=ent, unk1=u1, hash=hsh, flags=flags, a=f[0:3], b=f[3:6], c=g, s=s,
                        rest=rest.hex(), params=params))
        q += 0x4c + n * 8
    return out


def parse_collision(c):
    """Chunk 0x2e/0x2f (FUN_000a63f0): the collision of the entity whose 0x0d/0x04 chunks follow it.

    u32 version (5 adds 0x10 header bytes), u16 node count, u16 triangle count, u16 count of 64-byte blocks; then
    the 64-byte blocks (int16 vertices, then 10 bytes a triangle, not decoded), the nodes (48 bytes: float3 min,
    u32 a, float3 max, u32 b, float3 centre, float scale), the triangles (4 x u16: three int16 offsets of vertices
    in the leaf's blocks, offset of its 10 bytes), then one byte a triangle (surface flags, not decoded).
    Nodes form a tree: inner a = child indices (hi16, lo16), b = 0; leaf a = first triangle << 16 | 0x8000 |
    block count, b = first block << 16 | end triangle. Vertex = int16 * scale + centre.
    Inferred from the data, not from the collision code: checked by every vertex landing in its leaf's box and the
    leaves covering every triangle once (outside_box, triangles_read).
    """
    ver = struct.unpack_from('<I', c, 0)[0]
    n_nodes, n_tris, n_blocks = struct.unpack_from('<3H', c, 4)
    p = 0x1c if ver == 5 else 0x0c
    blocks = p
    p += n_blocks * 64
    nodes = []
    for k in range(n_nodes):
        mn = struct.unpack_from('<3f', c, p + k * 48)
        a = struct.unpack_from('<I', c, p + k * 48 + 12)[0]
        mx = struct.unpack_from('<3f', c, p + k * 48 + 16)
        b = struct.unpack_from('<I', c, p + k * 48 + 28)[0]
        ctr = struct.unpack_from('<3f', c, p + k * 48 + 32)
        sc = struct.unpack_from('<f', c, p + k * 48 + 44)[0]
        nodes.append(dict(min=mn, max=mx, a=a, b=b, centre=ctr, scale=sc))
    p += n_nodes * 48
    tris = [struct.unpack_from('<4H', c, p + k * 8) for k in range(n_tris)]
    p += n_tris * 8
    flags = list(c[p:p + n_tris])
    out_v, out_t, out_f, bad = [], [], [], 0
    covered = 0
    for nd in nodes:
        if not nd['a'] & 0x8000:
            continue  # inner node: a = child indices (hi16, lo16), b = 0
        t0, t1 = nd['a'] >> 16, nd['b'] & 0xFFFF
        boff = blocks + (nd['b'] >> 16) * 64
        covered += t1 - t0
        cache = {}
        for k in range(t0, t1):
            face = []
            for w in tris[k][:3]:
                if w not in cache:
                    q = struct.unpack_from('<3h', c, boff + w * 2)
                    v = tuple(q[i] * nd['scale'] + nd['centre'][i] for i in range(3))
                    if any(v[i] < nd['min'][i] - 0.05 or v[i] > nd['max'][i] + 0.05 for i in range(3)):
                        bad += 1
                    cache[w] = len(out_v)
                    out_v.append(v)
                face.append(cache[w])
            out_t.append(tuple(face))
            out_f.append(flags[k] if k < len(flags) else 0)
    return dict(version=ver, nodes=len(nodes), vertices=out_v, triangles=out_t, flags=out_f,
                outside_box=bad, triangles_declared=n_tris, triangles_read=covered)


def parse_geo(geo):
    res = dict(textures=[], meshes=[], entities=[], placements=[], other=[], collision={})
    pending = None
    for t, off, c in chunks(geo):
        if t == 0x18:
            res['textures'].append(parse_kxt(c))
        elif t in (0x2e, 0x2f):
            pending = parse_collision(c)
        elif t == 0x0d:
            res['meshes'].append(parse_kxe(c))
        elif t == 0x04:
            if pending is not None:
                res['collision'][len(res['entities'])] = pending
                pending = None
            res['entities'].append(parse_entity(c))
        elif t == 0x1a:
            res['placements'] = parse_placements(c)
        elif t not in (0x1d,):
            res['other'].append(dict(type=t, offset=off, size=len(c) + 4, raw=c))
    return res


def strip_triangles(indices, start, count):
    """D3D triangle strip: triangle k = (s[k], s[k+1], s[k+2]), odd k swapped; degenerate ones dropped."""
    s = indices[start:start + count + 2]
    out = []
    for k in range(count):
        a, b, c = s[k], s[k + 1], s[k + 2]
        if a == b or b == c or a == c:
            continue
        out.append((a, b, c) if k % 2 == 0 else (b, a, c))
    return out
