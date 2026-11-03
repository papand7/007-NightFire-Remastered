"""Import check + preview renders in Blender (headless):
blender -b --factory-startup --python tools/map_export/validation/blender_check.py -- <map dir>

Imports map.glb and collision.glb with Blender's glTF importer, prints object/triangle/material counts and the
bounds, and renders map_persp.png, map_top.png and collision_persp.png into <map dir>/validation/.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

d = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
out = os.path.join(d, 'validation')
os.makedirs(out, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def stats(tag):
    objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(min(a, b) for a, b in zip(lo, w))
            hi = Vector(max(a, b) for a, b in zip(hi, w))
    mats = len([m for m in bpy.data.materials if m.users])
    imgs = len([i for i in bpy.data.images if i.size[0] > 0])
    print('CHECK %s objects=%d mesh_objects=%d triangles=%d materials=%d images=%d bounds=%s..%s' % (
        tag, len(bpy.context.scene.objects), len(objs), tris, mats, imgs, tuple(round(x, 2) for x in lo),
        tuple(round(x, 2) for x in hi)))
    return lo, hi


def render(name, lo, hi, top):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in [e.identifier for e in
                                                              bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    sc.render.filepath = os.path.join(out, name)
    world = bpy.data.worlds.new('w')
    world.color = (0.6, 0.65, 0.7)
    sc.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    sc.collection.objects.link(sun)
    ctr, size = (lo + hi) / 2, (hi - lo)
    r = max(size) * 0.9
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    cam.data.clip_end = r * 10
    if top:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = max(size.x, size.y) * 1.05
        cam.location = (ctr.x, ctr.y, hi.z + r)
        cam.rotation_euler = (0, 0, 0)
    else:
        cam.location = ctr + Vector((r * 0.8, -r * 0.8, r * 0.6))
        cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(cam)
    sc.camera = cam
    bpy.ops.render.render(write_still=True)


for f, tag in (('map.glb', 'map'), ('collision.glb', 'collision')):
    reset()
    bpy.ops.import_scene.gltf(filepath=os.path.join(d, f))
    stats(tag)
    # previews without the sky dome, which encloses the map, and without the blocking polys
    hide = set()
    for o in bpy.context.scene.objects:
        if o.name.lower().replace('col_', '').startswith('sky'):
            hide.add(o)
        if o.name == 'blocking_polys':
            hide.update(o.children_recursive)
            hide.add(o)
    for o in hide:
        bpy.data.objects.remove(o)
    lo, hi = stats(tag + '_no_sky')
    render(tag + '_persp.png', lo, hi, False)
    if tag == 'map':
        render(tag + '_top.png', lo, hi, True)
