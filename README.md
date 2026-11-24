# Pterodon BES Importer for Blender 2.78

A Blender 2.78 add-on that imports **`.BES`** files, the 3D model/scene format used by the Pterodon engine
of **Vietcong** (2003).

The format was reverse-engineered from the official **BesImport** plugin for 3ds Max 8
(`besImport.dli` / `BstImport.dli`) by disassembling it, and then checked against real `.BES` files.
There is no official public specification of the format.

> **Status:** version 0.2. Tested on **Windows 7** with **Blender 2.78** using real Vietcong `.BES` files
> (format version `0008`). See [Known limitations](#known-limitations).

---

## Table of contents

1. [Features](#features)
2. [Origin of the BES format](#origin-of-the-bes-format)
3. [BES file structure and offsets](#bes-file-structure-and-offsets)
4. [How the data is organised](#how-the-data-is-organised)
5. [Installation (Blender 2.78 / Windows 7)](#installation-blender-278--windows-7)
6. [Usage and options](#usage-and-options)
7. [Tested on](#tested-on)
8. [Known limitations](#known-limitations)
9. [Development and tests](#development-and-tests)
10. [Credits and disclaimer](#credits-and-disclaimer)

---

## Features

- Node hierarchy (parent/child) with the original world transforms
- Meshes: vertices, normals, faces, one or more UV channels
- Several geometry blocks per object merged into a single mesh, one Blender material per block
- Instanced objects share the same mesh data
- Materials: diffuse / specular / opacity / two-sided / faceted flags and texture names
- Texture lookup next to the `.bes`, in a `tex/` sub-folder, in parent folders, or in a folder you choose
  (case-insensitive, tries `.tga .dds .jpg .bmp .png`)
- Dummies, cameras, lights, and sound/particle/IK-joint markers (imported as empties with custom properties)
- An import log written to a Blender text datablock (`bes_import_log`)

---

## Origin of the BES format

**BES** is the native 3D model/scene format of the engine behind **Vietcong**, the Vietnam War first-person
shooter released in 2003 and developed by the Czech studio **Pterodon** (co-produced with Illusion Softworks).
Game assets are authored in 3ds Max with a set of developer plugins, which is where the "Ptero" names in the
files come from: `PteroMat`, `PteroLayer`, `Ptero Light`, `Ptero IK Joint`, `Ptero SoundEvent` and
`Ptero ParticleEvent`.

**Author.** The importer's own error messages tell the user to "call **Beny**" when a file has an unsupported
version, which points to *Beny* as the author/maintainer of the format and of the 3ds Max tools. The community
specification project [vc-spec](https://github.com/FlashX64/vc-spec) lists BES as *"BenyErikSolitude"*, which looks like
a combination of developer nicknames. Neither source gives a full name, so none is stated here, and the name
expansion is a community observation, not an official statement.

**Other tools.** The same plugin family contains an importer for `.BST` files (`BstImport.dli`), which also reads BES
data. This add-on only handles `.BES`.

**Versions.** The version is stored as 4 ASCII characters: `0005`, `0006`, `0007`, `0008`, `0100`.
The original 3ds Max importer treats `0008` and `0100` as current and reports `0005`–`0007` as
"old BES format version, not yet supported".

---

## BES file structure and offsets

All values are **little-endian**. Offsets inside a block are relative to the start of that block.

Confidence legend: **[A]** read directly from the plugin's assembly, **[I]** inferred, **[?]** unknown.

### File header

| Offset | Size | Content | |
|---|---|---|---|
| `0x00` | 4 | Signature `"BES\0"` | A |
| `0x04` | 4 | Version as ASCII, e.g. `"0008"` | A |
| `0x08` | 8 | Not used by the importer (the two sample files contain ASCII `"0310"` and a small integer) | ? |
| `0x10` | – | First block, **only for version `0005`** | A |
| `0x10`…`0x300F` | 12288 | Reserved/unknown area in versions other than `0005` (skipped by the original importer) | ? |
| `0x3010` | – | First block, **for all other versions** | A |

### Generic block

```
+0x00  u32  block id
+0x04  u32  block size (bytes, header included, children included)
...
```

The next block starts at `block start + size`. This rule is used at the top level, inside nodes, inside
`GOBJ` and inside geometry blocks. Unknown blocks can therefore always be skipped safely.

### Block ids

| Id | Block | Where |
|---|---|---|
| `0x01`, `0x50` | Node | top level / inside a node |
| `0x70` | Info (user, comment) | top level |
| `0x1000` | Material list | inside the root node in the sample files; also accepted at top level |
| `0x1001`–`0x1004` | Materials | inside the material list |
| `0x20` | Light (3ds Max light) | inside a node |
| `0x25` | Light (Ptero light) | inside a node |
| `0x30` | GOBJ (geometry object) | inside a node |
| `0x31` | Geometry block (`GBlock`) | inside GOBJ |
| `0x32` | Vertices | inside GBlock |
| `0x33` | Faces | inside GBlock |
| `0x34` | User properties (text) | inside a node / GOBJ |
| `0x35` | Transform matrix (TM) | inside a node / GOBJ |
| `0x36` | Instance reference | inside GOBJ |
| `0x38` | Dummy | inside a node |
| `0x40` | Camera | inside a node |
| `0x65` | IK joint | inside a node |
| `0x66` | Sound event | inside a node |
| `0x67` | Particle event | inside a node |
| `0x80` | `PHYS_DATA` (ignored by the original importer) | inside a node |

### Info block (`0x70`) [A]

| Offset | Content |
|---|---|
| `+0x0C` | u32 length of the comment |
| `+0x14` | user string (`0x40` bytes) |
| `+0x54` | comment string |

### Node (`0x01` / `0x50`) [A]

| Offset | Content |
|---|---|
| `+0x00` | id (`0x01` or `0x50`) |
| `+0x04` | size of the whole node, children included |
| `+0x08` | u32 count (only logged by the original importer) |
| `+0x0C` | u32 `nameLen` (includes the terminating NUL) |
| `+0x10` | node name, NUL-terminated |
| `+0x10+nameLen` … `size` | sub-blocks (child nodes use the same block ids) |

### Transform block `0x35` (size `0x6C`) [A]

| Offset | Content |
|---|---|
| `+0x08` … `+0x2B` | 9 floats, not used by the original importer [?] |
| `+0x2C` | row 0, 3 floats (X axis) |
| `+0x3C` | row 1, 3 floats (Y axis) |
| `+0x4C` | row 2, 3 floats (Z axis) |
| `+0x5C` | row 3, 3 floats (translation) |

Rows are 16 bytes apart (3 floats + 4 bytes padding). The matrix uses the 3ds Max convention (row vectors) and is
a **world-space** transform: the original plugin applies it to the node and then attaches the node to its parent
while keeping the world transform. In Blender the rows become the columns of the 4×4 matrix.

### GOBJ (`0x30`) [A]

| Offset | Content |
|---|---|
| `+0x08` | u32 number of geometry blocks |
| `+0x0C` … `size` | sub-blocks: `0x31` geometry, `0x34` user properties, `0x35` TM, `0x36` instance |

Instance block `0x36` (size `0x0C`): `+0x08` u32 instance id. Objects that share an id share their mesh; the
later ones normally contain no geometry.

### Geometry block `0x31` [A]

| Offset | Content |
|---|---|
| `+0x08` | i32 material id (index in the material list, `-1` = none) |
| `+0x0C` … `size` | sub-blocks `0x32` (vertices) and `0x33` (faces) |

Several geometry blocks in one GOBJ form **one mesh**: vertices are appended, face indices are offset by the number
of vertices already present, and each block carries its own material.

### Vertex block `0x32` [A]

| Offset | Content |
|---|---|
| `+0x08` | u32 vertex count |
| `+0x0C` | u32 stride (bytes per vertex) |
| `+0x10` | u32 unknown [?] |
| `+0x14` | vertex data |

Per vertex (offsets relative to the start of the vertex):

| Offset | Content |
|---|---|
| `+0x00` | position, 3 × float |
| `+0x0C` | normal, 3 × float |
| `+0x18 + 8·k` | UV channel *k*, 2 × float |

The number of UV channels is `(stride − 0x18) / 8`. The file stores `v` top-down; the importer uses
`v_blender = 1 − v_file`.

### Face block `0x33` [A]

| Offset | Content |
|---|---|
| `+0x08` | u32 face count |
| `+0x0C` | faces, 3 × u32 vertex indices each (12 bytes per face) |

Faces are counter-clockwise, which matches Blender (no flipping is needed; checked against the vertex normals of
real files).

### Materials (index in the list == material id)

**`0x1000` material list:** `+0x08` u32 count, materials start at `+0x0C`, each one with its own `[id][size]`.

**`0x1003` / `0x1004` (PteroLayer)** [A] — note that several float fields are not 4-byte aligned:

| Offset | Content |
|---|---|
| `+0x08` | flags (bit 0 two-sided, bit 2 faceted) |
| `+0x0C` | number of textures |
| `+0x10` | surface (4 chars) |
| `+0x14` | transparency |
| `+0x18` / `+0x19` | grow type / grass type (bytes) |
| `+0x1A` | diffuse, 3 × float |
| `+0x26` | ambient, 3 × float |
| `+0x32` | specular, 3 × float |
| `+0x3E` | self-illumination, 3 × float |
| `+0x4A` | opacity |
| `+0x4E` | opacity falloff |
| `+0x52` | glossiness |
| `+0x56` | specular level |
| `+0x5A`, `+0x5E`, `+0x62` | lengths of three strings: shader type, shader file, material name |
| `+0x66` | the three strings, one after another; `0x1004` then has an extension block (water) before the textures |

Texture entry: `+0x00` layer, `+0x04` flags, `+0x10` move (3 floats), `+0x1C` name length, `+0x20` file name [A]. The
meaning of the flag bits (bit 4 mipmap, bit 20 environment, bit 22 lightmap-apply-light, bit 23 overlay
multitexture) is [I].

**`0x1002` (PteroMat)** [A/I]: `+0x08` flags, `+0x0C` texture-type bit mask, `+0x1C` name length, `+0x20` name, then one
`[flags][nameLen][name]` entry per set bit of the mask.

**`0x1001` (exFlags)** [A/I, confirmed on real files]: `+0x08` flags (bit 0 two-sided), `+0x10` texture-type bit mask,
textures from `+0x14`, each `[nameLen][flags][name at +0x08]`. These materials have no name; the add-on uses the
first texture's file name.

### Other node sub-blocks

| Id | Layout | |
|---|---|---|
| `0x34` | NUL-terminated user-property text at `+0x0C` | A/I |
| `0x38` dummy | `+0x08` size X, Y, Z (3 floats); drawn as a box of that size | A |
| `0x40` camera | `+0x08` FOV (radians), `+0x0C` position (3 floats), `+0x18` rotation X, Y, Z (3 floats) | A, rotation order/sign not verified |
| `0x20` 3ds Max light | `+0x08` type (1 omni, 2 free spot, 3 target spot, 4 directional, 5 target directional), `+0x14` RGB, `+0x20` intensity, `+0x30` TM rows | A/I |
| `0x25` Ptero light | `+0x08` enabled, `+0x0C` type, `+0x10` RGB, `+0x28` far attenuation end, `+0x2C` multiplier, `+0x30` hotspot, `+0x34` falloff, `+0x38` TM rows | A |
| `0x66` / `0x67` sound / particle event | `+0x08` id, `+0x0C` group, `+0x10` reference, `+0x14` impulse, `+0x18` interval, `+0x1C` random, `+0x20` TM rows | A |
| `0x65` IK joint | `+0x88` name of the connected object (A); other parameters not decoded | partial |

---

## How the data is organised

```
BES file
└── root node (0x01 / 0x50), usually "Scene Root"
    ├── material list (0x1000)          -> materials 0, 1, 2 ...
    ├── node  "Object"
    │   ├── GOBJ (0x30)
    │   │   ├── GBlock (0x31, material id 0) -> vertices (0x32) + faces (0x33)
    │   │   ├── GBlock (0x31, material id 1) -> vertices (0x32) + faces (0x33)
    │   │   ├── user properties (0x34)
    │   │   ├── TM (0x35)
    │   │   └── instance id (0x36)
    │   ├── child nodes ...              (same structure, recursive)
    │   └── dummies / lights / camera / events (0x38, 0x20, 0x25, 0x40, 0x66, 0x67)
    └── ...
```

- **Hierarchy:** nodes nest through block ids `0x01` / `0x50`. The add-on keeps the hierarchy by parenting Blender
  objects while preserving each node's world matrix.
- **Coordinates:** vertices are in the object's local space, in the 3ds Max coordinate system (right-handed, Z up),
  which is the same as Blender. **No axis swap is needed** (a bamboo model from the samples is about 6 m tall along Z).
- **Materials:** a geometry block refers to a material by its index in the material list. Faces of one block
  share that material; the add-on creates one Blender material slot per distinct id.
- **UVs:** stored per vertex, so UV indices equal vertex indices. UV values can exceed 1 (tiling); `v` is flipped.
- **Instances:** objects with the same instance id (`0x36`) are created as linked duplicates of one mesh.
- **Naming conventions seen in game data (presumed, not verified):** a leading `!` on a mesh name looks like a collision
  mesh (the add-on draws it as wireframe); `^PTC_*` and `flash_*` dummies look like particle/flash attachment points.

---

## Installation (Blender 2.78 / Windows 7)

### Option 1 – install from the zip (recommended)

1. Download **`io_import_bes.zip`** (do **not** unzip it).
2. Start Blender 2.78 and open **File → User Preferences…** (`Ctrl + Alt + U`).
3. Go to the **Add-ons** tab and click **Install from File…** (bottom of the window).
4. Select `io_import_bes.zip` and click **Install from File**.
5. In the add-on list, search for **BES** and tick the box next to
   **Import-Export: Pterodon BES format (.bes)**.
6. Click **Save User Settings** if you want the add-on to be enabled every time Blender starts.

### Option 2 – manual install

1. Unzip `io_import_bes.zip`. You get a folder named `io_import_bes` containing
   `__init__.py`, `bes_parser.py` and `import_bes.py`.
2. Copy that folder to:

   ```
   C:\Users\<your user name>\AppData\Roaming\Blender Foundation\Blender\2.78\scripts\addons\
   ```

   (`AppData` is a hidden folder; type `%APPDATA%` in the Windows Explorer address bar to open the Roaming folder.)
3. Restart Blender, open **File → User Preferences… → Add-ons**, search for **BES** and tick
   **Import-Export: Pterodon BES format (.bes)**.

### Updating

Remove the old add-on (untick it and click **Remove**), restart Blender, and install the new zip.

---

## Usage and options

**File → Import → Pterodon BES (.bes)**

The options currently have Portuguese labels in the file browser side panel:

| Label in Blender | Meaning |
|---|---|
| `Escala` | Global scale (default 1.0) |
| `Pasta de texturas` | Extra folder to search for textures |
| `Cameras` | Import cameras |
| `Luzes` | Import lights |
| `Dummies` | Import dummies |
| `Eventos (som/particulas/IK)` | Import sound/particle/IK markers as empties |
| `Escrever registo (Text editor)` | Write `bes_import_log` to the Text editor |

**Textures.** `.BES` files only store texture *names* (for example `NJK_Bamboo.tga`). Put the texture files next
to the `.bes`, in a `tex/` sub-folder, or set **Pasta de texturas**. Missing textures are reported in the log and
replaced by an empty image that you can re-point later.

**Render engine.** Materials and texture slots are created for **Blender Internal**; when the scene uses **Cycles**,
a basic image-texture node is added as well.

**Two-sided materials.** Blender Internal has *double sided* per mesh, not per material, so a mesh that contains
any two-sided material is displayed double sided.

---

## Tested on

- **Operating system:** Windows 7
- **Blender:** 2.78
- **Files:** real Vietcong `.BES` files, format version `0008`, with `0x1001` materials, several geometry blocks per
  object, LOD child nodes and dummies.

Not yet tested with real files: materials `0x1002`–`0x1004`, cameras, lights, IK joints, sound/particle events and
format versions `0005`–`0007`.

---

## Known limitations

- Only **import** is supported (no export).
- `.BST` files, animations (`.MANM`) and level files (`.SCO`) are not supported.
- The 12 KB area after the header in versions other than `0005`, the first 9 floats of the TM block and the field at
  `+0x10` of the vertex block are unknown and ignored.
- Camera rotation order/sign and Ptero light types are approximations.
- Format differences between versions `0005`–`0007` and `0008` are unknown; these versions are read on a best-effort
  basis and a warning is logged.
- The special UV channel re-ordering the original importer applies for some three-channel materials is not
  reproduced; channels are imported in file order (`UV0`, `UV1`, …).
- File vertex normals are applied on a best-effort basis (custom split normals when Blender allows it).

If you find a file that fails to import, please open an issue and attach the `.bes` (if you may share it) and the
`bes_import_log` text.

---

## Development and tests

```
io_import_bes/
├── __init__.py     # add-on registration and import operator
├── bes_parser.py   # pure-Python BES reader (no Blender dependency)
└── import_bes.py   # Blender side: objects, meshes, materials, textures
docs/
└── BES_format_notes.md
tests/
├── make_synthetic_bes.py    # builds a synthetic .bes following the format above
├── test_parser.py           # parser tests, run with plain Python 3
└── test_blender_glue.py     # importer tests using a simulated bpy/mathutils
```

Run the tests without Blender:

```
python tests/test_parser.py
python tests/test_blender_glue.py
```

The Blender-side test uses a simulated `bpy`, so it checks the importer logic only. Optional regression tests run
automatically if real `.BES` samples are placed in `tests/data/`.

---

## Credits and disclaimer

- Format knowledge comes from disassembling the 3ds Max plugin **BesImport / BstImport**, and was cross-checked with
  real `.BES` files. The community project [vc-spec](https://github.com/FlashX64/vc-spec) documents other
  Vietcong data formats and was used as background reference.
- This is an **independent, unofficial** project. It is not affiliated with or endorsed by Pterodon, Illusion
  Softworks, the publishers of Vietcong, or Autodesk.
- *Vietcong* and all related names are trademarks of their respective owners. No game assets are included in this
  repository; use the add-on only with files you are entitled to use.
