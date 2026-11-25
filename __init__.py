# -*- coding: utf-8 -*-
bl_info = {
    "name": "Pterodon BES format (.bes)",
    "author": "reconstruido a partir do plugin BesImport (3ds Max) de Petr Benysek",
    "version": (0, 2, 0),
    "blender": (2, 78, 0),
    "location": "File > Import > Pterodon BES (.bes)",
    "description": "Importa ficheiros .BES (malhas, hierarquia, materiais, luzes, cameras, dummies)",
    "warning": "Formato reconstruido por engenharia inversa; testar com ficheiros reais",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "import_bes" in locals():
        importlib.reload(import_bes)
    if "bes_parser" in locals():
        importlib.reload(bes_parser)

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper


class ImportBES(bpy.types.Operator, ImportHelper):
    """Importar um ficheiro Pterodon BES"""
    bl_idname = "import_scene.bes"
    bl_label = "Importar BES"
    bl_options = {'UNDO'}

    filename_ext = ".bes"
    filter_glob = StringProperty(default="*.bes;*.BES", options={'HIDDEN'})

    global_scale = FloatProperty(name="Escala", default=1.0, min=0.0001, max=10000.0)
    textures_path = StringProperty(name="Pasta de texturas", subtype='DIR_PATH', default="",
                                   description="Pasta adicional onde procurar texturas (procura tambem junto ao .bes e em tex/)")
    import_cameras = BoolProperty(name="Cameras", default=True)
    import_lights = BoolProperty(name="Luzes", default=True)
    import_dummies = BoolProperty(name="Dummies", default=True)
    import_events = BoolProperty(name="Eventos (som/particulas/IK)", default=True)
    write_log = BoolProperty(name="Escrever registo (Text editor)", default=True)

    def execute(self, context):
        from . import import_bes
        try:
            imp = import_bes.Importer(
                self, context, self.filepath, self.global_scale, self.textures_path,
                self.import_cameras, self.import_lights, self.import_dummies,
                self.import_events, self.write_log)
            imp.run()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "Falha ao importar BES: %s" % e)
            return {'CANCELLED'}
        self.report({'INFO'}, imp.log[-1] if imp.log else "BES importado")
        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportBES.bl_idname, text="Pterodon BES (.bes)")


def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
