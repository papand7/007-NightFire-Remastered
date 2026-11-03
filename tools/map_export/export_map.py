"""Export one NightFire (Xbox) level to GLB: python -I export_map.py <eurocom dir> <map name | level id> [out root]

Writes <out root>/<map>/map.glb, collision.glb, metadata.json, extraction_report.md and textures/*.png
(default out root generated/private/maps, git-ignored). Read-only: the game files are only read.

Coordinates: the game's are Direct3D's (left-handed, +Y up). glTF is right-handed, +Y up, so every position,
normal and translation has Z negated, triangle winding is reversed to keep faces pointing out, and rotations are
mirrored the same way. Units are kept 1:1 (game units; about a metre each judging by the cable car cabin, not
verified). Original values are kept in metadata.json.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nf_archive  # noqa: E402
import nf_geo  # noqa: E402
import nf_gltf  # noqa: E402
import nf_tex  # noqa: E402

# Multiplayer maps: the MP map table in default.xbe (file offset 0x16c698) and the English text (see README)
MAPS = {'skyrail': 0x07000024, 'fort_knox': 0x07000027, 'snow_blind': 0x07000029, 'phoenix_base': 0x07000026,
        'atlantis': 0x07000023, 'missile_silo': 0x07000028, 'sub_pen': 0x07000025, 'ravine': 0x0700004B}

# Placements of these entities are gameplay markers (spawns, pickups, grapple points); exported as empty nodes
# with their data, not as geometry. Chosen by name: an assumption, listed in the report.
MARKERS = ('mpstart', 'pickup', 'grapple', 'player', 'death')


def to_gl(p):
    return (p[0], p[1], -p[2])


def ypr_quat(pitch, yaw, roll):
    """D3DX yaw-pitch-roll (roll Z, then pitch X, then yaw Y) as a quaternion in the game's frame."""
    def q(axis, a):
        v = [0.0, 0.0, 0.0, math.cos(a / 2)]
        v[axis] = math.sin(a / 2)
        return v

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]
    return mul(mul(q(1, yaw), q(0, pitch)), q(2, roll))


def quat_to_gl(q):
    return [-q[0], -q[1], q[2], q[3]]


def unpack_normal(n):
    x, y, z = n & 0x7FF, (n >> 11) & 0x7FF, n >> 22
    x = x - 0x800 if x & 0x400 else x
    y = y - 0x800 if y & 0x400 else y
    z = z - 0x400 if z & 0x200 else z
    v = (x / 1023.0, y / 1023.0, z / 511.0)
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


def is_marker(name):
    return name.lower().startswith(MARKERS)


def export(eurocom, key, out_root):
    level = MAPS[key] if key in MAPS else int(key, 16)
    name = key if key in MAPS else '%08x' % level
    out = os.path.join(out_root, name)
    os.makedirs(os.path.join(out, 'textures'), exist_ok=True)
    arc = nf_archive.Archive(eurocom)
    fname = '%08x.bin' % level
    entry = arc.find(fname)
    data = arc.read(entry)
    subs = nf_geo.read_container(data)
    geo_sub = [s for s in subs if s['kind'] == 1]
    if len(geo_sub) != 1:
        raise SystemExit('expected one kind-1 geo file in %s, found %d' % (fname, len(geo_sub)))
    gs = geo_sub[0]
    g = nf_geo.parse_geo(data[gs['offset']:gs['offset'] + gs['size']])
    ents, meshes, pls = g['entities'], g['meshes'], g['placements']
    report = dict(level='0x%08x' % level, file=fname, geo_file=gs['name'], checks={}, notes=[])

    # textures
    gl = nf_gltf.Gltf()
    tex_index, tex_meta = {}, []
    for i, t in enumerate(g['textures']):
        rgba = nf_tex.decode(t)
        meta = dict(index=i, name=t['name'], width=t['width'], height=t['height'], format=t['format'],
                    mips=t['mips'], frames=t['frames'], global_slot_reference=t['reference'])
        if rgba:
            p = nf_tex.png(rgba, t['width'], t['height'])
            fn = '%03d_%s.png' % (i, ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in t['name']))
            with open(os.path.join(out, 'textures', fn), 'wb') as f:
                f.write(p)
            meta['png'] = 'textures/' + fn
            tex_index[i] = gl.image(p, t['name'])
        tex_meta.append(meta)
    materials = {}

    def material(tex, flags):
        k = (tex, flags)
        if k not in materials:
            t = g['textures'][tex] if tex < len(g['textures']) else None
            alpha = 'MASK' if t and t['format'] in ('DXT3', 'DXT5', 'A8R8G8B8', 'A4R4G4B4') else None
            materials[k] = gl.material('%s_%03x' % (t['name'] if t else 'tex%d' % tex, flags), tex_index.get(tex),
                                       alpha, extras=dict(texture=tex, group_flags=flags))
        return materials[k]

    # meshes (one glTF mesh per KXE, one primitive per texture/flags)
    gl_mesh, bad_idx, tri_total, degenerate = {}, 0, 0, 0
    for mi, m in enumerate(meshes):
        V = m['vertices']
        pos = [to_gl(v[:3]) for v in V]
        nrm = [to_gl(unpack_normal(v[3])) for v in V]
        col = [((v[4] >> 16) & 255, (v[4] >> 8) & 255, v[4] & 255, v[4] >> 24) for v in V]
        uv = [(v[5], v[6]) for v in V]
        by_mat, start = {}, 0
        for gr in m['groups']:
            tris = nf_geo.strip_triangles(m['indices'], start, gr['triangles'])
            degenerate += gr['triangles'] - len(tris)
            start += gr['triangles'] + 2
            by_mat.setdefault((gr['texture'], gr['flags']), []).extend(tris)
        if start != len(m['indices']):
            bad_idx += 1
        if not V or not by_mat:
            continue
        a_pos = gl.accessor(pos, 5126, 'VEC3', minmax=True, target=34962)
        a_nrm = gl.accessor(nrm, 5126, 'VEC3', target=34962)
        a_col = gl.accessor(col, 5121, 'VEC4', normalized=True, target=34962)
        a_uv = gl.accessor(uv, 5126, 'VEC2', target=34962)
        prims = []
        for (tex, flags), tris in by_mat.items():
            idx = [i for a, b, c in tris for i in (a, c, b)]  # mirrored Z: reverse winding
            if max(idx) >= len(V):
                bad_idx += 1
                continue
            tri_total += len(tris)
            prims.append(dict(attributes=dict(POSITION=a_pos, NORMAL=a_nrm, COLOR_0=a_col, TEXCOORD_0=a_uv),
                              indices=gl.accessor(idx, 5125 if len(V) > 65535 else 5123, 'SCALAR', target=34963),
                              material=material(tex, flags)))
        ename = ents[mi]['name'] if mi < len(ents) else 'mesh%d' % mi
        gl_mesh[mi] = gl.mesh(ename, prims)
    report['checks'].update(meshes=len(meshes), entities=len(ents), groups_index_mismatch=bad_idx,
                            triangles=tri_total, degenerate_strip_joins=degenerate)

    # placements: geometry nodes, marker empties
    def blocking(ei):
        # every group textured "Blocking_poly": invisible blocking geometry (by name, an assumption)
        m = meshes[ei]
        names = {g['textures'][x['texture']]['name'] for x in m['groups'] if x['texture'] < len(g['textures'])}
        return names == {'Blocking_poly'}

    geo_nodes, marker_nodes, block_nodes, pl_meta, markers = [], [], [], [], []
    for pi, p in enumerate(pls):
        en = ents[p['entity']]['name'] if p['entity'] < len(ents) else None
        q = ypr_quat(*p['b'])
        rec = dict(index=pi, entity=p['entity'], entity_name=en, flags='0x%x' % p['flags'], position=p['a'],
                   euler_xyz=p['b'], stored_quaternion=p['c'], scale=p.get('s'), params=p['params'],
                   unk1=p['unk1'], hash=p['hash'])
        pl_meta.append(rec)
        extras = dict(placement=pi, flags=rec['flags'], entity=p['entity'])
        nm = '%s_%d' % (en or 'marker', pi)
        if en is None or is_marker(en):
            markers.append(rec)
            marker_nodes.append(gl.node(nm, t=to_gl(p['a']), r=quat_to_gl(q), extras=extras, root=False))
        elif p['entity'] in gl_mesh:
            n = gl.node(nm, gl_mesh[p['entity']], t=to_gl(p['a']), r=quat_to_gl(q), extras=extras, root=False)
            (block_nodes if blocking(p['entity']) else geo_nodes).append(n)
    gl.node('geometry', children=geo_nodes)
    if block_nodes:
        gl.node('blocking_polys', children=block_nodes,
                extras=dict(note='meshes textured only with Blocking_poly; probably invisible in game (unverified)'))
    if marker_nodes:
        gl.node('gameplay_markers', children=marker_nodes,
                extras=dict(note='empties; orientation convention unverified, see extraction_report.md'))
    gl.write(os.path.join(out, 'map.glb'))

    # collision: one mesh per entity with collision, placed like the entity
    cg = nf_gltf.Gltf()
    cmat = cg.material('collision', double=True, color=[0.9, 0.3, 0.2, 1.0])
    cmesh, ctris, outside = {}, 0, 0
    for ei, c in g['collision'].items():
        if not c['triangles']:
            continue
        outside += c['outside_box']
        idx = [i for a, b, cc in c['triangles'] for i in (a, cc, b)]
        prim = dict(attributes=dict(POSITION=cg.accessor([to_gl(v) for v in c['vertices']], 5126, 'VEC3',
                                                         minmax=True, target=34962)),
                    indices=cg.accessor(idx, 5125, 'SCALAR', target=34963), material=cmat)
        cmesh[ei] = cg.mesh('col_' + ents[ei]['name'], [prim], extras=dict(surface_flags=sorted(set(c['flags']))))
        ctris += len(c['triangles'])
    cnodes = []
    for pi, p in enumerate(pls):
        if p['entity'] in cmesh and not is_marker(ents[p['entity']]['name']):
            cnodes.append(cg.node('col_%s_%d' % (ents[p['entity']]['name'], pi), cmesh[p['entity']],
                                  t=to_gl(p['a']), r=quat_to_gl(ypr_quat(*p['b'])), root=False))
    cg.node('collision', children=cnodes)
    cg.write(os.path.join(out, 'collision.glb'))
    report['checks'].update(collision_entities=len(cmesh), collision_triangles=ctris,
                            collision_vertices_outside_leaf_box=outside,
                            collision_triangles_declared=sum(c['triangles_declared'] for c in g['collision'].values()),
                            collision_triangles_covered=sum(c['triangles_read'] for c in g['collision'].values()))

    # bounds of the placed geometry (game frame)
    lo, hi = [1e30] * 3, [-1e30] * 3
    for p in pls:
        if p['entity'] < len(meshes) and not is_marker(ents[p['entity']]['name']):
            for v in meshes[p['entity']]['vertices']:
                for k in range(3):
                    x = v[k] + p['a'][k]
                    lo[k], hi[k] = min(lo[k], x), max(hi[k], x)
    report['checks']['placed_geometry_bounds_game'] = [lo, hi]

    meta = dict(level=report['level'], map=name, source=dict(archive_entry=fname, geo_file=gs['name'],
                                                             container_entries=len(subs)),
                coordinate_system=dict(game='Direct3D left-handed, +Y up', gltf='right-handed, +Y up',
                                       conversion='z -> -z, winding reversed, quaternion (x,y,z,w) -> (-x,-y,z,w)',
                                       units='game units 1:1 (about a metre, unverified)'),
                textures=tex_meta,
                entities=[dict(index=i, name=e['name'], hash=e['hash'], flags=e['flags'], bbox_min=e['bbox_min'],
                               bbox_max=e['bbox_max'], has_collision=i in g['collision'],
                               vertices=len(meshes[i]['vertices']) if i < len(meshes) else 0)
                          for i, e in enumerate(ents)],
                placements=pl_meta,
                spawn_points=[m for m in markers if (m['entity_name'] or '').lower().startswith('mpstart')],
                undecoded_chunks=[dict(type='0x%02x' % o['type'], offset=o['offset'], size=o['size'])
                                  for o in g['other'] if o['type'] not in (0x2e, 0x2f)],
                checks=report['checks'])
    with open(os.path.join(out, 'metadata.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    write_report(out, meta)
    return out, meta


def write_report(out, meta):
    """extraction_report.md: everything in it comes from metadata.json of the same run."""
    c, tx = meta['checks'], meta['textures']
    missing = [t['name'] for t in tx if not t.get('png')]
    lo, hi = c['placed_geometry_bounds_game']
    L = ['# %s (%s) extraction report' % (meta['map'], meta['level']), '',
         '- Source: `%s`, geo sub-file `%s`' % (meta['source']['archive_entry'], meta['source']['geo_file']),
         '- Coordinates: %s; glTF %s; %s. Units: %s.' % (
             meta['coordinate_system']['game'], meta['coordinate_system']['gltf'],
             meta['coordinate_system']['conversion'], meta['coordinate_system']['units']),
         '- Meshes: %d (entities %d), triangles %d, group/index count mismatches %d' % (
             c['meshes'], c['entities'], c['triangles'], c['groups_index_mismatch']),
         '- Placements: %d, of which %d gameplay markers (spawn points: %d)' % (
             len(meta['placements']), sum(1 for p in meta['placements']
                                          if p['entity_name'] is None or is_marker(p['entity_name'])),
             len(meta['spawn_points'])),
         '- Placed geometry bounds (game frame): %s to %s' % (
             [round(x, 1) for x in lo], [round(x, 1) for x in hi]),
         '- Textures: %d, %d embedded as PNG, %d without pixels in this file%s' % (
             len(tx), len(tx) - len(missing), len(missing), (': ' + ', '.join(missing)) if missing else ''),
         '- Collision: %d entities, %d triangles (%d declared, %d covered by BVH leaves), '
         '%d vertices outside their leaf box' % (
             c['collision_entities'], c['collision_triangles'], c['collision_triangles_declared'],
             c['collision_triangles_covered'], c['collision_vertices_outside_leaf_box']),
         '- Chunks not decoded: ' + (', '.join('%s (%d bytes)' % (u['type'], u['size'])
                                               for u in meta['undecoded_chunks']
                                               if u['type'] not in ('0x10', '0x1a', '0x1d')) or 'none'),
         '', '## Assumptions (not verified against the running game)', '',
         '- Gameplay markers are chosen by entity name (%s) and exported as empty nodes.' % ', '.join(MARKERS),
         '- Marker rotation convention: D3DX yaw-pitch-roll of the stored euler angles.',
         '- Meshes textured only with `Blocking_poly` are grouped under `blocking_polys` (probably invisible).',
         '- Collision BVH layout is inferred from FUN_000a63f0; surface flags are kept but not interpreted.',
         '- No comparison with an in-game capture yet; Godot import not tested.']
    with open(os.path.join(out, 'extraction_report.md'), 'w') as f:
        f.write('\n'.join(L) + '\n')


if __name__ == '__main__':
    root = sys.argv[3] if len(sys.argv) > 3 else os.path.join('generated', 'private', 'maps')
    o, m = export(sys.argv[1], sys.argv[2], root)
    print(o, json.dumps(m['checks']))
