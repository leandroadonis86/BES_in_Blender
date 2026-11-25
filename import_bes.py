# -*- coding: utf-8 -*-
"""Parte Blender do importador BES (Blender 2.78 / API 2.7x)."""
import os
import math
import bpy
from mathutils import Matrix, Vector

from . import bes_parser


def max_tm_to_blender(rows, scale=1.0):
    """4 linhas Max (r0,r1,r2,t) -> Matrix 4x4 do Blender (colunas)."""
    r0, r1, r2, t = rows
    return Matrix((
        (r0[0], r1[0], r2[0], t[0] * scale),
        (r0[1], r1[1], r2[1], t[1] * scale),
        (r0[2], r1[2], r2[2], t[2] * scale),
        (0.0, 0.0, 0.0, 1.0)))


# ---------------------------------------------------------------- texturas
_IMG_EXT = ('', '.tga', '.dds', '.jpg', '.jpeg', '.bmp', '.png')


def _ci_find(directory, name):
    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    low = name.lower()
    for e in entries:
        if e.lower() == low:
            return os.path.join(directory, e)
    return None


def find_texture(fname, search_dirs):
    fname = fname.replace('\\', '/')
    base = os.path.basename(fname)
    stem, ext = os.path.splitext(base)
    names = [base] + [stem + e for e in _IMG_EXT[1:] if (stem + e) != base]
    for d in search_dirs:
        for sub in ('', 'tex', 'Tex', 'TEX', 'textures'):
            dd = os.path.join(d, sub) if sub else d
            if not os.path.isdir(dd):
                continue
            for nm in names:
                hit = _ci_find(dd, nm)
                if hit:
                    return hit
    return None


class Importer(object):
    def __init__(self, operator, context, filepath, scale, textures_path,
                 import_cameras, import_lights, import_dummies, import_events,
                 write_log):
        self.op = operator
        self.ctx = context
        self.scene = context.scene
        self.filepath = filepath
        self.scale = scale
        self.import_cameras = import_cameras
        self.import_lights = import_lights
        self.import_dummies = import_dummies
        self.import_events = import_events
        self.write_log = write_log
        self.log = []
        base = os.path.dirname(filepath)
        self.search_dirs = []
        if textures_path:
            self.search_dirs.append(textures_path)
        self.search_dirs += [base, os.path.dirname(base), os.path.dirname(os.path.dirname(base))]
        self.mat_cache = {}
        self.inst_cache = {}
        self.images = {}
        self.stats = dict(objects=0, meshes=0, faces=0, materials=0, missing_tex=0)

    def say(self, msg):
        self.log.append(msg)

    # ------------------------------------------------------------ materiais
    def get_image(self, fname):
        if fname in self.images:
            return self.images[fname]
        path = find_texture(fname, self.search_dirs)
        img = None
        if path:
            try:
                img = bpy.data.images.load(path, check_existing=True)
            except Exception as e:
                self.say('erro a carregar %s: %s' % (path, e))
        if img is None:
            self.stats['missing_tex'] += 1
            self.say('textura nao encontrada: %s' % fname)
            img = bpy.data.images.new(os.path.basename(fname) or 'missing', 4, 4)
            img.filepath = fname
        self.images[fname] = img
        return img

    def get_material(self, bes, idx):
        if idx < 0 or idx >= len(bes.materials):
            return None
        if idx in self.mat_cache:
            return self.mat_cache[idx]
        m = bes.materials[idx]
        mat = bpy.data.materials.new(m.name or 'bes_mat_%d' % idx)
        mat.diffuse_color = m.diffuse
        mat.diffuse_intensity = 1.0
        mat.specular_color = m.specular
        mat.specular_intensity = max(0.0, min(1.0, m.spec_level / 100.0 if m.spec_level > 1.0 else m.spec_level))
        mat.emit = max(m.selfillum) if m.selfillum else 0.0
        if m.opacity < 0.999:
            mat.use_transparency = True
            mat.alpha = max(0.0, min(1.0, m.opacity))
        mat['bes_kind'] = m.kind
        mat['bes_two_sided'] = m.two_sided
        mat['bes_faceted'] = m.faceted
        if m.shader_type:
            mat['bes_shader'] = m.shader_type
        if m.shader_file:
            mat['bes_shader_file'] = m.shader_file
        use_cycles = self.scene.render.engine == 'CYCLES'
        if use_cycles:
            try:
                mat.use_nodes = True
            except Exception:
                use_cycles = False
        for ti, t in enumerate(m.textures):
            if not t.get('file'):
                continue
            img = self.get_image(t['file'])
            tex = bpy.data.textures.new('%s_t%d' % (mat.name, ti), 'IMAGE')
            tex.image = img
            slot = mat.texture_slots.add()
            slot.texture = tex
            slot.texture_coords = 'UV'
            slot.uv_layer = 'UV%d' % min(ti, 7)
            if ti > 0 or t.get('lm_apply_light'):
                slot.use_map_color_diffuse = ti == 0
                slot.blend_type = 'MULTIPLY'
            if use_cycles and ti == 0:
                try:
                    nt = mat.node_tree
                    node = nt.nodes.new('ShaderNodeTexImage')
                    node.image = img
                    bsdf = nt.nodes.get('Diffuse BSDF')
                    if bsdf is not None:
                        nt.links.new(node.outputs['Color'], bsdf.inputs['Color'])
                except Exception as e:
                    self.say('nos Cycles falharam: %s' % e)
            t['_blender_image'] = img.name
        self.stats['materials'] += 1
        self.mat_cache[idx] = mat
        return mat

    # --------------------------------------------------------------- malhas
    def build_mesh(self, bes, node):
        md = node.mesh
        s = self.scale
        me = bpy.data.meshes.new(node.name)
        verts = [(v[0] * s, v[1] * s, v[2] * s) for v in md.verts]
        me.from_pydata(verts, [], md.faces)
        slot_of = {}
        for mi in md.face_mat:
            if mi not in slot_of:
                mat = self.get_material(bes, mi)
                slot_of[mi] = len(me.materials)
                me.materials.append(mat)
        nuv = len(md.uvs)
        for c in range(nuv):
            layer = me.uv_textures.new('UV%d' % c)
            uvd = me.uv_layers[layer.name].data
            uvs = md.uvs[c]
            for pi, poly in enumerate(me.polygons):
                for li, vi in zip(poly.loop_indices, poly.vertices):
                    uvd[li].uv = uvs[vi]
        for pi, poly in enumerate(me.polygons):
            if pi < len(md.face_mat):
                poly.material_index = slot_of.get(md.face_mat[pi], 0)
                mat = me.materials[poly.material_index] if len(me.materials) else None
                poly.use_smooth = not bool(mat and mat.get('bes_faceted', False))
        me.update(calc_edges=True)
        # normais do ficheiro (melhor esforco; nao critico)
        try:
            me.normals_split_custom_set_from_vertices([tuple(n) for n in md.normals])
            me.use_auto_smooth = True
        except Exception:
            pass
        for mat in me.materials:
            if mat is not None and mat.get('bes_two_sided', False):
                me.show_double_sided = True
        self.stats['meshes'] += 1
        self.stats['faces'] += len(md.faces)
        return me

    # ----------------------------------------------------------------- nos
    def make_object(self, bes, node):
        kind = node.kind
        data = None
        if kind == 'mesh':
            md = node.mesh
            if node.instance_id is not None and node.instance_id in self.inst_cache and not md.faces:
                data = self.inst_cache[node.instance_id]
            elif md.faces:
                data = self.build_mesh(bes, node)
                if node.instance_id is not None:
                    self.inst_cache[node.instance_id] = data
            else:
                kind = 'empty'
        elif kind == 'camera':
            if not self.import_cameras:
                return None
            data = bpy.data.cameras.new(node.name)
            fov = node.props.get('fov', 0.0)
            if 0.01 < fov < 3.1:
                data.angle = fov
        elif kind == 'light':
            if not self.import_lights:
                return None
            p = node.props
            lt = {'omni': 'POINT', 'spot': 'SPOT', 'sun': 'SUN'}.get(p.get('ltype'), 'POINT')
            data = bpy.data.lamps.new(node.name, lt)
            col = p.get('color', (1, 1, 1))
            data.color = tuple(max(0.0, min(1.0, c)) for c in col)
            data.energy = max(0.0, p.get('energy', 1.0))
        elif kind in ('dummy',):
            if not self.import_dummies:
                return None
        elif kind in ('sound', 'particle', 'ikjoint'):
            if not self.import_events:
                return None
        obj = bpy.data.objects.new(node.name, data)
        if data is None:
            if kind == 'dummy':
                obj.empty_draw_type = 'CUBE'
                sz = node.props.get('size', (1, 1, 1))
                obj.empty_draw_size = max(0.001, max(sz) * 0.5 * self.scale)
                obj['bes_dummy_size'] = tuple(sz)
            else:
                obj.empty_draw_type = 'PLAIN_AXES'
                obj.empty_draw_size = 0.2 * max(self.scale, 1e-6) * 10 if kind != 'empty' else 0.1
        self.scene.objects.link(obj)
        obj['bes_kind'] = kind
        if kind == 'mesh' and node.name.startswith('!'):
            obj.draw_type = 'WIRE'      # convencao presumida: '!' = malha de colisao
            obj['bes_collision_guess'] = True
        if node.userprops:
            obj['bes_userprops'] = node.userprops
        for k, v in node.props.items():
            if isinstance(v, (int, float, str)):
                obj['bes_' + k] = v
            elif isinstance(v, tuple):
                obj['bes_' + k] = list(v)
        self.stats['objects'] += 1
        return obj

    def build_node(self, bes, node, parent_obj, parent_world):
        obj = self.make_object(bes, node)
        world = parent_world
        if node.tm is not None:
            world = max_tm_to_blender(node.tm, self.scale)
        elif node.kind == 'camera':
            world = self.camera_world(node)
        if obj is not None:
            obj.matrix_basis = world
            if parent_obj is not None:
                obj.parent = parent_obj
                obj.matrix_parent_inverse = parent_world.inverted()
            my_obj, my_world = obj, world
        else:
            my_obj, my_world = parent_obj, parent_world
        for ch in node.children:
            self.build_node(bes, ch, my_obj, my_world)

    def camera_world(self, node):
        p = node.props
        ax, ay, az = p.get('rot', (0, 0, 0))
        m = Matrix.Rotation(ax, 4, 'X') * Matrix.Rotation(ay, 4, 'Y') * Matrix.Rotation(az, 4, 'Z')
        pos = p.get('pos', (0, 0, 0))
        m.translation = Vector(pos) * self.scale
        return m

    # ------------------------------------------------------------------ run
    def run(self):
        bes = bes_parser.parse_file(self.filepath)
        self.say('BES versao %s' % bes.version)
        for w in bes.warnings:
            self.say('AVISO: ' + w)
        if bes.unknown_blocks:
            self.say('blocos desconhecidos: %d (ex.: %s)' % (len(bes.unknown_blocks), bes.unknown_blocks[:5]))
        base = os.path.splitext(os.path.basename(self.filepath))[0]
        root = bpy.data.objects.new(base, None)
        root.empty_draw_type = 'PLAIN_AXES'
        self.scene.objects.link(root)
        if bes.info_user or bes.info_comment:
            root['bes_info_user'] = bes.info_user
            root['bes_info_comment'] = bes.info_comment
        for n in bes.roots:
            self.build_node(bes, n, root, Matrix.Identity(4))
        self.scene.update()
        self.say('importado: %(objects)d objectos, %(meshes)d malhas, %(faces)d faces, '
                 '%(materials)d materiais, %(missing_tex)d texturas em falta' % self.stats)
        if self.write_log:
            t = bpy.data.texts.new('bes_import_log')
            t.write('\n'.join(self.log))
        return bes
