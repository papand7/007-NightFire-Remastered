"""List the archive, or unpack level files: python -I nf_unpack.py <eurocom dir> [out dir] [level id ...]

Read-only: writes only into the out dir (keep it under generated/private, which git ignores).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nf_archive import Archive  # noqa: E402


def level_names(arc):
    """Level files the index has, by brute force over "<id>.bin" names (0x07 = default.xbe's levels)."""
    found = {}
    for n in range(0x400):
        name = '%08x.bin' % (0x07000000 | n)
        e = arc.find(name)
        if e:
            found[name] = e
    return found


def main():
    arc = Archive(sys.argv[1])
    levels = level_names(arc)
    if len(sys.argv) == 2:
        for name, e in sorted(levels.items()):
            print(name, 'entry %3d' % e['index'], 'part d%02d' % e['part'], 'stored %#x' % e['stored'],
                  'unpacked %#x' % e['unpacked'])
        print('%d entries, %d named levels' % (len(arc.entries), len(levels)))
        return
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    want = ['%08x.bin' % int(a, 16) for a in sys.argv[3:]] or sorted(levels)
    for name in want:
        e = arc.find(name)
        if not e:
            print('not in archive:', name)
            continue
        data = arc.read(e)
        with open(os.path.join(out, name), 'wb') as f:
            f.write(data)
        print('unpacked', name, len(data))
    with open(os.path.join(out, 'index.json'), 'w') as f:
        json.dump({'levels': {n: e['index'] for n, e in levels.items()}, 'entries': arc.entries}, f, indent=1)


if __name__ == '__main__':
    main()
