# -*- coding: utf-8 -*-
"""
bes_parser.py - leitor de ficheiros .BES (Pterodon / "BesImport" de Petr Benysek)

Python puro (sem bpy), para poder ser testado fora do Blender.
O formato foi reconstruido por analise do plugin besImport.dli / BstImport.dli
(3ds Max). Ver docs/BES_format_notes.md para o grau de confianca de cada campo.

Regras gerais (confirmadas no assembly):
  * ficheiro = "BES\\0" + versao ASCII de 4 chars + (cabecalho) + blocos
  * bloco    = [id:u32][size:u32] ...  ; o proximo bloco esta em inicio+size
  * todos os valores little-endian
"""
import struct

# ---- IDs de blocos -------------------------------------------------------
ID_NODE_A = 0x01
ID_NODE_B = 0x50
ID_LIGHT_MAX = 0x20
ID_LIGHT_PTERO = 0x25
ID_GOBJ = 0x30
ID_GBLOCK = 0x31
ID_VERTS = 0x32
ID_FACES = 0x33
ID_USERPROPS = 0x34
ID_TM = 0x35
ID_INSTANCE = 0x36
ID_DUMMY = 0x38
ID_CAMERA = 0x40
ID_IKJOINT = 0x65
ID_SOUND = 0x66
ID_PARTICLE = 0x67
ID_INFO = 0x70
ID_PHYS = 0x80
ID_MATLIST = 0x1000
ID_MAT_EX = 0x1001      # material "exFlags" (sem nome)
ID_MAT_PTERO = 0x1002   # PteroMat (mascara texTypes)
ID_MAT_LAYER = 0x1003   # PteroLayer
ID_MAT_LAYER2 = 0x1004  # PteroLayer + extensao (agua)

KNOWN_TOP = (ID_NODE_A, ID_NODE_B, ID_INFO, ID_MATLIST)
SUPPORTED_VERSIONS = ('0005', '0006', '0007', '0008', '0100')


class BESError(Exception):
    pass


class Node(object):
    def __init__(self, name):
        self.name = name
        self.kind = 'empty'      # empty|mesh|dummy|camera|light|sound|particle|ikjoint
        self.tm = None           # 4 linhas x 3 floats (convencao Max, linhas)
        self.userprops = ''
        self.children = []
        self.mesh = None         # MeshData
        self.instance_id = None
        self.props = {}          # dados extra (luz, camara, ...)


class MeshData(object):
    def __init__(self):
        self.verts = []          # (x,y,z)
        self.normals = []
        self.uvs = []            # uvs[canal] = lista (u,v) por vertice (v ja convertido)
        self.faces = []          # (a,b,c)
        self.face_mat = []       # indice de material (ou -1) por face
        self.nverts_per_gblock = []


class Material(object):
    def __init__(self):
        self.kind = 'layer'
        self.name = ''
        self.flags = 0
        self.diffuse = (0.8, 0.8, 0.8)
        self.ambient = (0.8, 0.8, 0.8)
        self.specular = (0.0, 0.0, 0.0)
        self.selfillum = (0.0, 0.0, 0.0)
        self.opacity = 1.0
        self.glossiness = 0.0
        self.spec_level = 0.0
        self.two_sided = False
        self.faceted = False
        self.shader_type = ''
        self.shader_file = ''
        self.textures = []       # dicts: {file, layer, flags, ...}
        self.tex_types = 0


class BESFile(object):
    def __init__(self):
        self.version = ''
        self.info_user = ''
        self.info_comment = ''
        self.materials = []
        self.roots = []
        self.warnings = []
        self.unknown_blocks = []


def _cstr(data, off, maxlen=None):
    end = len(data) if maxlen is None else min(len(data), off + maxlen)
    z = data.find(b'\0', off, end)
    if z < 0:
        z = end
    try:
        return data[off:z].decode('cp1252', 'replace')
    except Exception:
        return ''


def _u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def _i32(data, off):
    return struct.unpack_from('<i', data, off)[0]


def _f32(data, off):
    return struct.unpack_from('<f', data, off)[0]


def _f3(data, off):
    return struct.unpack_from('<3f', data, off)


def _popcount(v):
    return bin(v & 0xFFFFFFFF).count('1')


def _read_tm_rows(data, off, stride=0x10):
    """4 linhas de 3 floats com 'stride' bytes entre linhas."""
    return [_f3(data, off + i * stride) for i in range(4)]


class _Reader(object):
    def __init__(self, data, bf):
        self.d = data
        self.bf = bf
        self.n = len(data)

    def warn(self, msg):
        self.bf.warnings.append(msg)

    def hdr(self, pos, limit):
        """(id,size) do bloco em pos, validado; None se invalido."""
        if pos + 8 > limit:
            return None
        bid, size = struct.unpack_from('<II', self.d, pos)
        if size < 8 or pos + size > limit:
            return None
        return bid, size


# ---- materiais -------------------------------------------------------------

def _parse_tex_layer(d, p, end, layerstyle):
    """Entrada de textura dos materiais 0x1003/0x1004: cabecalho 0x20 + nome."""
    if p + 0x20 > end:
        return None, end
    layer = _u32(d, p)
    flags = _u32(d, p + 4)
    nlen = _u32(d, p + 0x1c)
    if nlen > 0x400 or p + 0x20 + nlen > end:
        return None, end
    t = {
        'layer': layer, 'flags': flags,
        'p8': _u32(d, p + 8), 'pc': _u32(d, p + 0xc),
        'move': _f3(d, p + 0x10),
        'file': _cstr(d, p + 0x20, nlen),
        'mipmap': bool(flags & 0x10),
        'overlay_multitex': bool(flags & (1 << 23)),
        'lm_apply_light': bool(flags & (1 << 22)),
        'env': bool(flags & (1 << 20)),
    }
    return t, p + 0x20 + nlen


def _parse_mat_layer(d, p, size, bf, ext):
    m = Material()
    m.kind = 'layer2' if ext else 'layer'
    end = p + size
    if size < 0x66:
        raise BESError('material curto')
    m.flags = _u32(d, p + 8)
    ntex = _u32(d, p + 0xc)
    m.two_sided = bool(m.flags & 1)
    m.faceted = bool(m.flags & 4)
    m.diffuse = _f3(d, p + 0x1a)
    m.ambient = _f3(d, p + 0x26)
    m.specular = _f3(d, p + 0x32)
    m.selfillum = _f3(d, p + 0x3e)
    op = _f32(d, p + 0x4a)
    m.opacity = op / 100.0 if op > 1.5 else op
    m.glossiness = _f32(d, p + 0x52)
    m.spec_level = _f32(d, p + 0x56)
    l1, l2, l3 = _u32(d, p + 0x5a), _u32(d, p + 0x5e), _u32(d, p + 0x62)
    if l1 + l2 + l3 > size:
        raise BESError('comprimentos de string invalidos')
    s = p + 0x66
    m.shader_type = _cstr(d, s, l1)
    m.shader_file = _cstr(d, s + l1, l2)
    m.name = _cstr(d, s + l1 + l2, l3)
    q = s + l1 + l2 + l3
    if ext:   # extensao (agua): [?][size]...
        if q + 8 <= end:
            esz = _u32(d, q + 4)
            if 8 <= esz <= end - q:
                q += esz
    if ntex > 64:
        raise BESError('numTex absurdo (%d)' % ntex)
    for _ in range(ntex):
        t, q = _parse_tex_layer(d, q, end, True)
        if t is None:
            bf.warnings.append('material "%s": textura truncada' % m.name)
            break
        m.textures.append(t)
    m.textures.sort(key=lambda t: t['layer'])
    return m


def _parse_mat_ptero(d, p, size, bf):
    m = Material()
    m.kind = 'ptero'
    end = p + size
    m.flags = _u32(d, p + 8)
    m.tex_types = _u32(d, p + 0xc)
    m.two_sided = bool(m.flags & 1)
    m.faceted = bool(m.flags & 4)
    nlen = _u32(d, p + 0x1c)
    if nlen > 0x400 or p + 0x20 + nlen > end:
        raise BESError('nome de material invalido')
    m.name = _cstr(d, p + 0x20, nlen)
    q = p + 0x20 + nlen
    ntex = _popcount(m.tex_types)
    for i in range(ntex):
        if q + 8 > end:
            bf.warnings.append('material "%s": texturas truncadas' % m.name)
            break
        fl = _u32(d, q)
        ln = _u32(d, q + 4)
        if ln > 0x400 or q + 8 + ln > end:
            break
        m.textures.append({'layer': i, 'flags': fl, 'file': _cstr(d, q + 8, ln),
                           'mipmap': bool(fl & 0x10), 'overlay_multitex': False,
                           'lm_apply_light': False, 'env': False})
        q += 8 + ln
    return m


def _parse_mat_ex(d, p, size, bf):
    m = Material()
    m.kind = 'ex'
    end = p + size
    m.flags = _u32(d, p + 8)
    m.tex_types = _u32(d, p + 0x10)
    m.two_sided = bool(m.flags & 1)
    m.faceted = bool(m.flags & 4)
    q = p + 0x14
    for i in range(_popcount(m.tex_types)):
        if q + 8 > end:
            break
        ln = _u32(d, q)
        fl = _u32(d, q + 4)
        if ln > 0x400 or q + 8 + ln > end:
            break
        m.textures.append({'layer': i, 'flags': fl, 'file': _cstr(d, q + 8, ln),
                           'mipmap': False, 'overlay_multitex': False,
                           'lm_apply_light': False, 'env': False})
        q += 8 + ln
    m.name = ''
    return m


def _parse_matlist(rd, pos, size):
    d, bf = rd.d, rd.bf
    count = _u32(d, pos + 8)
    q = pos + 0xc
    end = pos + size
    for i in range(count):
        h = rd.hdr(q, end)
        if h is None:
            rd.warn('lista de materiais truncada no material %d' % i)
            break
        mid, msz = h
        try:
            if mid == ID_MAT_LAYER:
                m = _parse_mat_layer(d, q, msz, bf, False)
            elif mid == ID_MAT_LAYER2:
                m = _parse_mat_layer(d, q, msz, bf, True)
            elif mid == ID_MAT_PTERO:
                m = _parse_mat_ptero(d, q, msz, bf)
            elif mid == ID_MAT_EX:
                m = _parse_mat_ex(d, q, msz, bf)
            else:
                rd.warn('material desconhecido 0x%X' % mid)
                m = Material()
                m.name = 'unknown_%X' % mid
        except (BESError, struct.error) as e:
            rd.warn('material %d (0x%X) ilegivel: %s' % (i, mid, e))
            m = Material()
            m.name = 'broken_%d' % i
        if not m.name:
            if m.textures and m.textures[0].get('file'):
                import os as _os
                m.name = _os.path.splitext(_os.path.basename(m.textures[0]['file'].replace('\\', '/')))[0]
            else:
                m.name = 'bes_mat_%d' % len(bf.materials)
        bf.materials.append(m)       # mantem o indice == matID
        q += msz


# ---- geometria -------------------------------------------------------------

def _parse_gblock(rd, pos, size, mesh):
    d = rd.d
    end = pos + size
    mat_id = _i32(d, pos + 8)
    base_v = len(mesh.verts)
    # nota: faces e vertices vem em sub-blocos 0x32 / 0x33
    q = pos + 0xc
    pend_faces = []
    nuv_this = 0
    while q + 8 <= end:
        h = rd.hdr(q, end)
        if h is None:
            rd.warn('sub-bloco invalido em gblock @%d' % q)
            break
        sid, ssz = h
        if sid == ID_VERTS:
            nv = _u32(d, q + 8)
            stride = _u32(d, q + 0xc)
            data0 = q + 0x14
            if stride < 0x18 or data0 + nv * stride > q + ssz:
                rd.warn('bloco de vertices inconsistente (nv=%d stride=%d)' % (nv, stride))
                nv = max(0, min(nv, (q + ssz - data0) // max(stride, 1)))
            nuv_this = min(max(0, (stride - 0x18) // 8), 8)
            while len(mesh.uvs) < nuv_this:
                mesh.uvs.append([(0.0, 0.0)] * len(mesh.verts))
            for i in range(nv):
                o = data0 + i * stride
                mesh.verts.append(_f3(d, o))
                mesh.normals.append(_f3(d, o + 12))
                for c in range(len(mesh.uvs)):
                    if c < nuv_this:
                        u, v = struct.unpack_from('<2f', d, o + 0x18 + 8 * c)
                        mesh.uvs[c].append((u, 1.0 - v))
                    else:
                        mesh.uvs[c].append((0.0, 0.0))
        elif sid == ID_FACES:
            nf = _u32(d, q + 8)
            f0 = q + 0xc
            if f0 + nf * 12 > q + ssz:
                rd.warn('bloco de faces inconsistente')
                nf = max(0, (q + ssz - f0) // 12)
            for i in range(nf):
                pend_faces.append(struct.unpack_from('<3I', d, f0 + 12 * i))
        else:
            rd.bf.unknown_blocks.append(('gblock', sid, q))
        q += ssz
    nv_total = len(mesh.verts)
    for (a, b, c) in pend_faces:
        a += base_v
        b += base_v
        c += base_v
        if a >= nv_total or b >= nv_total or c >= nv_total or a == b or b == c or a == c:
            rd.warn('face invalida/degenerada ignorada (%d,%d,%d)' % (a, b, c))
            continue
        mesh.faces.append((a, b, c))
        mesh.face_mat.append(mat_id)


def _parse_gobj(rd, pos, size, node):
    d = rd.d
    end = pos + size
    mesh = MeshData()
    q = pos + 0xc
    while q + 8 <= end:
        h = rd.hdr(q, end)
        if h is None:
            rd.warn('sub-bloco invalido em GOBJ @%d' % q)
            break
        sid, ssz = h
        if sid == ID_GBLOCK:
            _parse_gblock(rd, q, ssz, mesh)
        elif sid == ID_USERPROPS:
            node.userprops = _cstr(d, q + 0xc, ssz - 0xc)
        elif sid == ID_TM:
            node.tm = _read_tm_rows(d, q + 0x2c)
        elif sid == ID_INSTANCE:
            node.instance_id = _u32(d, q + 8)
        else:
            rd.bf.unknown_blocks.append(('gobj', sid, q))
        q += ssz
    node.kind = 'mesh'
    node.mesh = mesh


def _parse_node(rd, pos, size, parent_list, depth=0):
    d = rd.d
    if depth > 200:
        rd.warn('hierarquia demasiado funda')
        return
    nlen = _u32(d, pos + 0xc)
    if nlen > 0x400 or 0x10 + nlen > size:
        rd.warn('nome de no invalido @%d' % pos)
        return
    node = Node(_cstr(d, pos + 0x10, nlen))
    parent_list.append(node)
    end = pos + size
    q = pos + 0x10 + nlen
    while q + 8 <= end:
        h = rd.hdr(q, end)
        if h is None:
            rd.warn('sub-bloco invalido em no "%s" @%d' % (node.name, q))
            break
        sid, ssz = h
        try:
            if sid in (ID_NODE_A, ID_NODE_B):
                _parse_node(rd, q, ssz, node.children, depth + 1)
            elif sid == ID_GOBJ:
                _parse_gobj(rd, q, ssz, node)
            elif sid == ID_MATLIST:      # no ficheiro real a lista esta dentro do no raiz
                _parse_matlist(rd, q, ssz)
            elif sid == ID_TM:
                node.tm = _read_tm_rows(d, q + 0x2c)
            elif sid == ID_USERPROPS:
                node.userprops = _cstr(d, q + 0xc, ssz - 0xc)
            elif sid == ID_DUMMY:
                node.kind = 'dummy'
                node.props['size'] = _f3(d, q + 8)
            elif sid == ID_CAMERA:
                node.kind = 'camera'
                node.props.update(fov=_f32(d, q + 8), pos=_f3(d, q + 0xc),
                                  rot=_f3(d, q + 0x18))
            elif sid == ID_LIGHT_MAX:
                node.kind = 'light'
                ltype = _u32(d, q + 8)
                node.props.update(
                    ptero=False, ltype={1: 'omni', 2: 'spot', 3: 'spot', 4: 'sun', 5: 'sun'}.get(ltype, 'omni'),
                    raw_type=ltype, color=_f3(d, q + 0x14), energy=_f32(d, q + 0x20))
                node.tm = _read_tm_rows(d, q + 0x30)
            elif sid == ID_LIGHT_PTERO:
                node.kind = 'light'
                node.props.update(
                    ptero=True, enabled=_u32(d, q + 8), raw_type=_u32(d, q + 0xc),
                    color=_f3(d, q + 0x10), far_atten_end=_f32(d, q + 0x28),
                    energy=_f32(d, q + 0x2c), hotspot=_f32(d, q + 0x30),
                    falloff=_f32(d, q + 0x34), cast_shadows=_u32(d, q + 0x20))
                node.tm = _read_tm_rows(d, q + 0x38)
            elif sid in (ID_SOUND, ID_PARTICLE):
                node.kind = 'sound' if sid == ID_SOUND else 'particle'
                node.props.update(id=_u32(d, q + 8), group=_u32(d, q + 0xc),
                                  name_id=_u32(d, q + 0x10), impulse=_u32(d, q + 0x14),
                                  interval=_f32(d, q + 0x18), random=_f32(d, q + 0x1c))
                node.tm = _read_tm_rows(d, q + 0x20)
            elif sid == ID_IKJOINT:
                node.kind = 'ikjoint'
                node.props['object_a'] = _cstr(d, q + 0x88, ssz - 0x88) if ssz > 0x88 else ''
            elif sid == ID_PHYS:
                node.props['phys_data_bytes'] = ssz
            else:
                rd.bf.unknown_blocks.append(('node', sid, q))
        except struct.error as e:
            rd.warn('bloco 0x%X truncado em "%s": %s' % (sid, node.name, e))
        q += ssz


def _find_data_start(d, version, bf):
    n = len(d)
    guess = 0x10 if version == '0005' else 0x3010
    cands = [guess] + [x for x in (0x10, 0x3010) if x != guess]
    for c in cands:
        if c + 8 <= n:
            bid, size = struct.unpack_from('<II', d, c)
            if bid in KNOWN_TOP and 8 <= size <= n - c:
                if c != guess:
                    bf.warnings.append('inicio de dados em 0x%X (esperado 0x%X)' % (c, guess))
                return c
    # procura por varrimento (ultimo recurso)
    for c in range(0x10, min(n - 8, 0x4000), 4):
        bid, size = struct.unpack_from('<II', d, c)
        if bid in KNOWN_TOP and 8 <= size <= n - c:
            bf.warnings.append('inicio de dados encontrado por varrimento em 0x%X' % c)
            return c
    raise BESError('nao foi possivel localizar o primeiro bloco')


def parse(data):
    bf = BESFile()
    if len(data) < 0x18 or data[:4] != b'BES\0':
        raise BESError('Nao e um ficheiro BES (assinatura invalida)')
    bf.version = data[4:8].decode('ascii', 'replace')
    if bf.version not in SUPPORTED_VERSIONS:
        bf.warnings.append('versao BES desconhecida: %r (tentando na mesma)' % bf.version)
    elif bf.version in ('0005', '0006', '0007'):
        bf.warnings.append('versao antiga %s: o plugin original tambem a marca como nao suportada' % bf.version)
    rd = _Reader(data, bf)
    pos = _find_data_start(data, bf.version, bf)
    n = len(data)
    while pos + 8 <= n:
        h = rd.hdr(pos, n)
        if h is None:
            bf.warnings.append('bloco de topo invalido em %d - fim da leitura' % pos)
            break
        bid, size = h
        try:
            if bid in (ID_NODE_A, ID_NODE_B):
                _parse_node(rd, pos, size, bf.roots)
            elif bid == ID_INFO:
                bf.info_user = _cstr(data, pos + 0x14, 0x40)
                clen = _u32(data, pos + 0xc)
                bf.info_comment = _cstr(data, pos + 0x54, clen if clen < 0x4000 else None)
            elif bid == ID_MATLIST:
                _parse_matlist(rd, pos, size)
            else:
                bf.unknown_blocks.append(('top', bid, pos))
        except struct.error as e:
            bf.warnings.append('bloco de topo 0x%X truncado: %s' % (bid, e))
        pos += size
    return bf


def parse_file(path):
    with open(path, 'rb') as f:
        return parse(f.read())
