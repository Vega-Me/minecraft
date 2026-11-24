"""Execute with exec(compile(source, absolute_script_path, 'exec')) in Blender.
Creates a NEW scene; never deletes existing content. Saves only a separate preview.
"""
from pathlib import Path
import importlib.util
import json
import math
import bpy
from mathutils import Vector, Euler

# compile filename is available even if MCP exec has no __file__ (or a stale one).
import inspect
SCRIPT = Path(inspect.currentframe().f_code.co_filename).resolve()
if not (SCRIPT.parent / 'sample_guts_locomotion.py').exists():
    raise RuntimeError('Execute the saved script using compile(source, absolute_script_path, "exec").')
ROOT = SCRIPT.parents[1]
OUTPUT = Path(globals().get('GUTS_PREVIEW_OUTPUT', ROOT / 'texture-packs/previews/guts-locomotion/Guts_Locomotion_Preview.blend'))
spec = importlib.util.spec_from_file_location('guts_offline_sampler', SCRIPT.parent / 'sample_guts_locomotion.py')
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)
data = sampler.export(ROOT, ROOT / 'texture-packs/previews/guts-locomotion')
reference = ROOT / 'texture-packs/previews/guts-locomotion/vanilla-humanoid.geo.json'
if not reference.exists(): reference = Path('/private/tmp/guts-animation-review/vanilla-humanoid.geo.json')
humanoid = json.loads(reference.read_text())['minecraft:geometry'][0]['bones']
sword = json.loads((ROOT / 'texture-packs/Guts/models/entity/ikux_greatsword_back.geo.json').read_text())['minecraft:geometry'][0]['bones']
scene = bpy.data.scenes.new('Guts Locomotion — isolated preview')
if bpy.context.window: bpy.context.window.scene = scene
scene.render.fps = 60
scene.frame_start, scene.frame_end = 1, 2000
scene['source_sha256'] = data['sha256']
scene['caveat'] = data['notes']
scene['coordinate_mapping'] = 'MC (x,y,z) -> Blender (x,-z,y)/16; Bedrock rotation signs (-X,-Y,+Z), reordered XZY -> Blender (-X,-Z,-Y).'
scene.world = bpy.data.worlds.new('Guts preview world')
scene.world.color = (.12, .12, .12)

def xyz(v): return Vector((v[0]/16, -v[2]/16, v[1]/16))
def rotation(v): return Euler(tuple(math.radians(x) for x in (-v[0], -v[2], -v[1])), 'XZY')
def material(name, color, metallic=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    shader = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = .45
    return m
neutral = material('Neutral vanilla humanoid', (.48, .51, .55))
steel = material('Actual Guts sword geometry — steel gray', (.3, .34, .4), .65)
floor_mat = material('Floor', (.065, .08, .1))

def empty(name, parent=None, location=(0,0,0)):
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_mode = 'XZY'
    return obj

# Mesh vertices are authored directly: no operators or dependence on selected objects.
def cube(name, definition, bone, pivot, mat):
    origin, size = definition['origin'], definition['size']
    inflate = definition.get('inflate', 0)
    cp = definition.get('pivot', pivot)
    cr = rotation(definition.get('rotation', [0,0,0])).to_matrix()
    vertices = []
    for x,y,z in ((0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)):
        p = [origin[i]-inflate + t*(size[i]+2*inflate) for i,t in enumerate((x,y,z))]
        vertices.append(cr @ (xyz(p)-xyz(cp)) + xyz(cp)-xyz(pivot))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.parent = bone
    obj.data.materials.append(mat)
    return obj

for mode, offset in [('WALK', -1.3), ('SPRINT', 1.3)]:
    group = empty(mode, location=(offset,0,0))
    definitions = {b['name']: b for b in humanoid}
    for b in sword:
        if b['name'] not in definitions: definitions[b['name']] = b
    objects = {}
    def build(name):
        if name in objects: return objects[name]
        b = definitions[name]
        parent_name = b.get('parent')
        parent = build(parent_name) if parent_name else group
        pivot = b.get('pivot', [0,0,0])
        pp = definitions[parent_name].get('pivot', [0,0,0]) if parent_name else [0,0,0]
        obj = empty(mode+'/'+name, parent, xyz(pivot)-xyz(pp))
        obj.rotation_euler = rotation(b.get('rotation', [0,0,0]))
        objects[name] = obj
        # Hide skin overlay layers; retain actual classic six-part base geometry.
        if name not in ('hat','jacket','leftSleeve','rightSleeve','leftPants','rightPants'):
            for i,c in enumerate(b.get('cubes', [])):
                cube(mode+'/'+name+'/'+str(i), c, obj, pivot, steel if name.startswith('ikux_') else neutral)
        return obj
    for name in definitions: build(name)
    rest = {name: obj.location.copy() for name,obj in objects.items()}
    # Each gait loops at its own true period, rather than restarting the sprint
    # mid-stride at the end of a two-second comparison clip.
    config = data['modes'][mode]
    period = .6667 / config['clock_rate']
    clips = json.loads((ROOT / 'texture-packs/Guts/animations/guts_locomotion.animation.json').read_text())['animations']
    frames = [sampler.pose(clips, i/60*period, config['speed_weight'],
                          config['sprinting'], config['clock_rate'],
                          1+i/60*period*scene.render.fps) for i in range(61)]
    for frame in frames:
        for name, channels in frame['bones'].items():
            if name not in objects: raise ValueError('Missing geometry bone: '+name)
            obj = objects[name]
            obj.location = rest[name] + xyz(channels['position'])
            base = definitions[name].get('rotation', [0,0,0])
            obj.rotation_euler = rotation([a+b for a,b in zip(base, channels['rotation'])])
            obj.keyframe_insert('location', frame=frame['frame'])
            obj.keyframe_insert('rotation_euler', frame=frame['frame'])
    # Blender 4.4+/5.x layered actions and older action compatibility.
    for obj in objects.values():
        if not obj.animation_data or not obj.animation_data.action: continue
        action = obj.animation_data.action
        curves = list(getattr(action, 'fcurves', []))
        for layer in getattr(action, 'layers', []):
            for strip in layer.strips:
                for bag in strip.channelbags: curves.extend(bag.fcurves)
        for curve in curves:
            for key in curve.keyframe_points: key.interpolation = 'LINEAR'
            curve.modifiers.new('CYCLES')
    text = bpy.data.curves.new(mode+' label', 'FONT')
    text.body = mode + ('  |  weight .45' if mode == 'WALK' else '  |  weight .80 / clock 1.18')+'\nActual Guts sword geometry (steel gray)'
    text.align_x = 'CENTER'
    text.size = .115
    obj = bpy.data.objects.new(mode+' label', text)
    scene.collection.objects.link(obj)
    obj.location = (offset, -.05, 2.65)
    obj.rotation_euler = (math.pi/2,0,0)
    text.materials.append(neutral)

cube('Preview floor', {'origin':[-80,-1,-64], 'size':[160,1,128]}, empty('Floor root'), [0,0,0], floor_mat)
camera_data = bpy.data.cameras.new('Preview camera')
camera = bpy.data.objects.new('Preview camera', camera_data)
scene.collection.objects.link(camera)
camera.location = (4,-8,4)
camera.rotation_euler = (Vector((0,0,1.3))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.type = 'ORTHO'
camera_data.ortho_scale = 6.8
scene.camera = camera
for name, location, energy, size in [('Key',(1,-4,6),1300,5),('Rim',(-3,3,5),1100,4)]:
    light = bpy.data.lights.new(name,'AREA')
    shapes = {item.identifier for item in light.bl_rna.properties['shape'].enum_items}
    light.energy, light.size = energy, size
    if 'DISK' in shapes: light.shape = 'DISK'
    obj = bpy.data.objects.new(name,light)
    scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
try:
    scene.render.engine = 'CYCLES'
except TypeError as error:
    print('Preview engine unavailable; retaining current engine:', error)
scene.cycles.samples = 32
scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
scene.render.resolution_percentage = 100
formats = {i.identifier for i in scene.render.image_settings.bl_rna.properties['file_format'].enum_items}
if 'PNG' not in formats:
    raise RuntimeError('PNG output unavailable: ' + repr(formats))
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = str(OUTPUT.with_name('Guts_Locomotion_Preview.png'))
scene.frame_set(12)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
# Write a new .blend library containing this scene and dependencies only.
# Unlike save_as_mainfile this does not change or save the user's current file.
bpy.data.libraries.write(str(OUTPUT), {scene}, fake_user=True, compress=True)
print('Saved isolated preview:', OUTPUT)
