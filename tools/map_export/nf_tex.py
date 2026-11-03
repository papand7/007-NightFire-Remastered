"""KXT pixels -> RGBA and PNG (top mip of the first frame only). Formats as chosen by FUN_000e4400."""
import struct
import zlib


def _565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _dxt(data, w, h, kind):
    out = bytearray(w * h * 4)
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    step = 8 if kind == 'DXT1' else 16
    p = 0
    for by in range(bh):
        for bx in range(bw):
            alpha = None
            if kind == 'DXT3':
                a = int.from_bytes(data[p:p + 8], 'little')
                alpha = [((a >> (4 * i)) & 15) * 17 for i in range(16)]
                p += 8
            elif kind == 'DXT5':
                a0, a1 = data[p], data[p + 1]
                bits = int.from_bytes(data[p + 2:p + 8], 'little')
                if a0 > a1:
                    tab = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
                else:
                    tab = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
                alpha = [tab[(bits >> (3 * i)) & 7] for i in range(16)]
                p += 8
            c0, c1, bits = struct.unpack_from('<HHI', data, p)
            p += 8
            r0, r1 = _565(c0), _565(c1)
            if c0 > c1 or kind != 'DXT1':
                cols = [r0 + (255,), r1 + (255,),
                        tuple((2 * r0[i] + r1[i]) // 3 for i in range(3)) + (255,),
                        tuple((r0[i] + 2 * r1[i]) // 3 for i in range(3)) + (255,)]
            else:
                cols = [r0 + (255,), r1 + (255,), tuple((r0[i] + r1[i]) // 2 for i in range(3)) + (255,), (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if x >= w or y >= h:
                    continue
                c = cols[(bits >> (2 * i)) & 3]
                o = (y * w + x) * 4
                out[o:o + 4] = bytes((c[0], c[1], c[2], alpha[i] if alpha else c[3]))
        if step and p > len(data):
            break
    return bytes(out)


def _unswizzle_index(x, y, w, h):
    """Xbox (NV2A) swizzle: bits of x and y interleaved, x first, until the smaller side runs out."""
    off, bit, sx, sy = 0, 0, 1, 1
    while sx < w or sy < h:
        if sx < w:
            off |= (x & sx) and (1 << bit)
            bit += 1
            sx <<= 1
        if sy < h:
            off |= (y & sy) and (1 << bit)
            bit += 1
            sy <<= 1
    return off


def _linear(data, w, h, fmt):
    bpp = 4 if fmt == 'A8R8G8B8' else 2
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            s = _unswizzle_index(x, y, w, h) * bpp
            if bpp == 4:
                b, g, r, a = data[s:s + 4]
            else:
                v = data[s] | data[s + 1] << 8
                if fmt == 'A4R4G4B4':
                    a, r, g, b = (v >> 12) * 17, ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17
                else:  # A1R5G5B5
                    a = 255 if v & 0x8000 else 0
                    r, g, b = ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31
            o = (y * w + x) * 4
            out[o:o + 4] = bytes((r, g, b, a))
    return bytes(out)


def decode(tex):
    w, h, fmt, px = tex['width'], tex['height'], tex['format'], tex['pixels']
    if tex.get('reference') is not None or not px:
        return None
    if fmt in ('DXT1', 'DXT3', 'DXT5'):
        return _dxt(px, w, h, fmt)
    if fmt in ('A8R8G8B8', 'A4R4G4B4', 'A1R5G5B5'):
        return _linear(px, w, h, fmt)
    return None


def png(rgba, w, h):
    raw = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))
