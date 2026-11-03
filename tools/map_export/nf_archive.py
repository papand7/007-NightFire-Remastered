"""Read-only access to NightFire's (Xbox, default.xbe) Eurocom archive eurocom/filesys.d00-d10.

Everything here was read from default.xbe (addresses are xbe2pe/Ghidra addresses of .local/game.exe):

Index (FUN_000e2a40): the first 0x13800 bytes of filesys.d00.
  header 8 x u32: [0] id, [1] CRC32 of the block with [1]=0, [2] counter, [3] d00 size, [6] entry count,
                  [7] archive part count (11)
  entries from +0x20, 0x26 bytes each, sorted by hash (binary search in FUN_000e2960):
    +0x00 u32 hash   CRC32 (FUN_000e8f90, table 0x1d52e8 = zlib's) of the lower-cased name, '/' -> '\\'
    +0x04 u32 ?      (not decoded)
    +0x08 u32 0
    +0x0C u64 offset into the parts d00..d10 laid end to end
    +0x14 u32 stored size
    +0x18 u32 unpacked size (rounded up to 4 by the loader)
    +0x1C u16 kind   2 = KXC packed, 4 / 0 = stored (observed, the reader of this field is not decoded)
    +0x1E u16 part   the filesys.dNN the data starts in (observed to agree with the offset)
    +0x20 u32 0, +0x24 u16 ? (not decoded)
Level files are "<id>.bin" with the level id in %8.8x (FUN_00011160, FUN_000be910), e.g. "07000011.bin".

KXC (FUN_000e8e30): "KXC" 04, u32 chunk count, then that many EDL chunks back to back.
EDL (FUN_000d4ac0 header, FUN_000d3a80 method 1): "EDL", flags (bit 7 = big endian, low 7 bits = method
0 stored / 1 Huffman LZ / 2 not seen), u32 packed size (with the 12 byte header), u32 unpacked size, then an
LSB-first bit stream. Method 1 is Deflate's LZ77 with Deflate's length/distance tables (checked against the
tables at 0x18cd5c, 0x18cd7c, 0x18cd9c, 0x18cdd8) but Eurocom's own block and code-length headers.
"""
import os
import struct
import zlib

INDEX_SIZE = 0x13800
ENTRY_SIZE = 0x26

LEN_BASE = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192,
            224, 255]
LEN_EXTRA = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]
DIST_BASE = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072,
             4096, 6144, 8192, 12288, 16384, 24576]
DIST_EXTRA = [0, 0, 0, 0] + [i // 2 for i in range(2, 28)]


def name_hash(name):
    return zlib.crc32(name.lower().replace('/', '\\').encode('latin1'))


class Bits:
    def __init__(self, data, pos):
        self.d = data
        self.p = pos
        self.buf = 0
        self.n = 0

    def need(self, k):
        while self.n < k:
            b = self.d[self.p] if self.p < len(self.d) else 0
            self.p += 1
            self.buf |= b << self.n
            self.n += 8

    def get(self, k):
        self.need(k)
        v = self.buf & ((1 << k) - 1)
        self.buf >>= k
        self.n -= k
        return v


def _build(lengths):
    """Canonical codes, shortest first then by symbol; LSB-first lookup on 15 bits -> (symbol << 4) | length."""
    table = [0] * (1 << 15)
    code = 0
    order = sorted((l, s) for s, l in enumerate(lengths) if l)
    prev = order[0][0] if order else 0
    for l, s in order:
        code <<= (l - prev)
        prev = l
        r = int(format(code, '0%db' % l)[::-1], 2)
        v = (s << 4) | l
        for k in range(r, 1 << 15, 1 << l):
            table[k] = v
        code += 1
    return table


def edl_unpack(data, pos=0):
    """Unpack one EDL chunk at data[pos:]; returns (bytes, packed size)."""
    if data[pos:pos + 3] != b'EDL':
        raise ValueError('no EDL at %#x' % pos)
    flags = data[pos + 3]
    if flags & 0x80:
        raise NotImplementedError('big-endian EDL')
    method = flags & 0x7F
    psize, usize = struct.unpack_from('<II', data, pos + 4)
    if method == 0:
        return bytes(data[pos + 12:pos + 12 + usize]), psize
    if method != 1:
        raise NotImplementedError('EDL method %d' % method)
    bs = Bits(data, pos + 12)
    out = bytearray()
    cur = 0  # FUN_000d3a80's local_8: the running code length, kept across trees and blocks
    lit = dist = None
    while True:
        if bs.get(1) == 0:
            n = bs.get(15)
            for _ in range(n):
                out.append(bs.get(8))
        else:
            for which in (0, 1):
                n = bs.get(9)
                if n:
                    lengths = []
                    for _ in range(n):
                        if bs.get(1):
                            cur = bs.get(4)
                        lengths.append(cur)
                    if which == 0:
                        lit = _build(lengths)
                    else:
                        dist = _build(lengths)
            while True:
                bs.need(15)
                v = lit[bs.buf & 0x7FFF]
                bs.buf >>= v & 15
                bs.n -= v & 15
                sym = v >> 4
                if sym < 256:
                    out.append(sym)
                    continue
                if sym == 256:
                    break
                sym -= 257
                length = LEN_BASE[sym] + 3 + bs.get(LEN_EXTRA[sym])
                bs.need(15)
                v = dist[bs.buf & 0x7FFF]
                bs.buf >>= v & 15
                bs.n -= v & 15
                ds = v >> 4
                back = DIST_BASE[ds] + bs.get(DIST_EXTRA[ds]) + 1
                start = len(out) - back
                if back >= length:
                    out += out[start:start + length]
                else:
                    for i in range(length):
                        out.append(out[start + i])
        if bs.get(1):
            break
    if len(out) != usize:
        raise ValueError('EDL unpacked %d bytes, header says %d' % (len(out), usize))
    return bytes(out), psize


def kxc_unpack(data):
    if data[:4] != b'KXC\x04':
        raise ValueError('not KXC')
    count = struct.unpack_from('<I', data, 4)[0]
    pos, out = 8, bytearray()
    for _ in range(count):
        chunk, psize = edl_unpack(data, pos)
        out += chunk
        pos += psize
    return bytes(out)


class Archive:
    def __init__(self, eurocom_dir):
        self.dir = eurocom_dir
        with open(os.path.join(eurocom_dir, 'filesys.d00'), 'rb') as f:
            self.index = f.read(INDEX_SIZE)
        h = struct.unpack_from('<8I', self.index, 0)
        self.count, self.parts = h[6], h[7]
        self.sizes = [os.path.getsize(self._part(i)) for i in range(self.parts)]
        self.starts = [sum(self.sizes[:i]) for i in range(self.parts)]
        self.entries = []
        for i in range(self.count):
            o = 0x20 + i * ENTRY_SIZE
            hsh, unk4, _, off, stored, unpacked, kind, part = struct.unpack_from('<IIIQIIHH', self.index, o)
            self.entries.append(dict(index=i, hash=hsh, unk4=unk4, offset=off, stored=stored, unpacked=unpacked,
                                     kind=kind, part=part))
        self.by_hash = {e['hash']: e for e in self.entries}

    def _part(self, i):
        return os.path.join(self.dir, 'filesys.d%02d' % i)

    def read_raw(self, e):
        off, left, out = e['offset'], e['stored'], bytearray()
        while left:
            i = max(k for k in range(self.parts) if self.starts[k] <= off)
            with open(self._part(i), 'rb') as f:
                f.seek(off - self.starts[i])
                c = f.read(min(left, self.sizes[i] - (off - self.starts[i])))
            if not c:
                raise IOError('archive ends early')
            out += c
            off += len(c)
            left -= len(c)
        return bytes(out)

    def read(self, e):
        raw = self.read_raw(e)
        return kxc_unpack(raw) if raw[:3] == b'KXC' else raw

    def find(self, name):
        return self.by_hash.get(name_hash(name))
