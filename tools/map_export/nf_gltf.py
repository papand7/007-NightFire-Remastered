"""Minimal glTF 2.0 binary (GLB) writer, no dependencies."""
import json
import struct


class Gltf:
    def __init__(self):
        self.j = dict(asset=dict(version='2.0', generator='nightfire-recomp tools/map_export'), scene=0,
                      scenes=[dict(nodes=[])], nodes=[], meshes=[], accessors=[], bufferViews=[], buffers=[],
                      materials=[], textures=[], images=[], samplers=[dict(wrapS=10497, wrapT=10497)])
        self.bin = bytearray()

    def _view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        v = dict(buffer=0, byteOffset=len(self.bin), byteLength=len(data))
        if target:
            v['target'] = target
        self.bin += data
        self.j['bufferViews'].append(v)
        return len(self.j['bufferViews']) - 1

    def accessor(self, values, ctype, typ, normalized=False, minmax=False, target=None):
        fmt = {5126: 'f', 5125: 'I', 5121: 'B', 5123: 'H'}[ctype]
        comps = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[typ]
        flat = [x for v in values for x in (v if comps > 1 else (v,))]
        a = dict(bufferView=self._view(struct.pack('<%d%s' % (len(flat), fmt), *flat), target),
                 componentType=ctype, count=len(values), type=typ)
        if normalized:
            a['normalized'] = True
        if minmax:
            cols = list(zip(*values)) if comps > 1 else [values]
            a['min'] = [min(c) for c in cols]
            a['max'] = [max(c) for c in cols]
        self.j['accessors'].append(a)
        return len(self.j['accessors']) - 1

    def image(self, png_bytes, name):
        self.j['images'].append(dict(bufferView=self._view(png_bytes), mimeType='image/png', name=name))
        self.j['textures'].append(dict(source=len(self.j['images']) - 1, sampler=0))
        return len(self.j['textures']) - 1

    def material(self, name, texture=None, alpha=None, double=False, extras=None, color=None):
        m = dict(name=name, pbrMetallicRoughness=dict(metallicFactor=0.0, roughnessFactor=1.0))
        if texture is not None:
            m['pbrMetallicRoughness']['baseColorTexture'] = dict(index=texture)
        if color:
            m['pbrMetallicRoughness']['baseColorFactor'] = color
        if alpha:
            m['alphaMode'] = alpha
        if double:
            m['doubleSided'] = True
        if extras:
            m['extras'] = extras
        self.j['materials'].append(m)
        return len(self.j['materials']) - 1

    def mesh(self, name, prims, extras=None):
        m = dict(name=name, primitives=prims)
        if extras:
            m['extras'] = extras
        self.j['meshes'].append(m)
        return len(self.j['meshes']) - 1

    def node(self, name, mesh=None, t=None, r=None, s=None, children=None, extras=None, root=True):
        n = dict(name=name)
        if mesh is not None:
            n['mesh'] = mesh
        if t and any(t):
            n['translation'] = list(t)
        if r and tuple(r) != (0, 0, 0, 1):
            n['rotation'] = list(r)
        if s and tuple(s) != (1, 1, 1):
            n['scale'] = list(s)
        if children:
            n['children'] = children
        if extras:
            n['extras'] = extras
        self.j['nodes'].append(n)
        i = len(self.j['nodes']) - 1
        if root:
            self.j['scenes'][0]['nodes'].append(i)
        return i

    def write(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j['buffers'] = [dict(byteLength=len(self.bin))]
        for k in ('materials', 'textures', 'images', 'meshes'):
            if not self.j[k]:
                del self.j[k]
        if 'textures' not in self.j:
            del self.j['samplers']
        js = json.dumps(self.j, separators=(',', ':')).encode()
        js += b' ' * (-len(js) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, 'wb') as f:
            f.write(struct.pack('<III', 0x46546C67, 2, total))
            f.write(struct.pack('<II', len(js), 0x4E4F534A) + js)
            f.write(struct.pack('<II', len(self.bin), 0x004E4942) + self.bin)
